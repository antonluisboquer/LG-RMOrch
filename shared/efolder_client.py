#!/usr/bin/env python3
"""
EfolderConnect Direct Process Client

A reusable client for extracting document fields from loan efolders.
Handles caching, automatic retries, and polling for async processing.

Usage:
    from shared.efolder_client import EfolderClient, ExtractionRequest

    request = ExtractionRequest(
        loan_number="2512953182",
        document_types=["Credit Report", "1003 URLA", "Title Report"],
    )

    client = EfolderClient()
    result = client.extract_documents(request)
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


API_BASE_URL = os.getenv("EFOLDER_API_BASE_URL", "https://1doxzxvey2.execute-api.us-west-1.amazonaws.com/prod")
API_TOKEN = os.getenv("EFOLDER_API_TOKEN", "esfuse-token")

ALL_DOCUMENT_TYPES = [
    "1003 URLA",
    "Credit Report",
    "Title Report",
    "Compliance Report",
    "Appraisal Report",
    "Purchase Agreement",
    "Evidence of Insurance",
    "Flood Insurance",
    "Flood Certificate",
    "Tax Summary",
    "Loan Estimate",
    "Appraisal Invoice",
    "Estimated Settlement Statement",
    "Closing Disclosure",
    "Approval Form",
    "Closing Protection Letter",
]


def _get_default_client_id() -> str:
    """Get default client_id based on ENCOMPASS_ENV environment variable."""
    env = os.getenv("ENCOMPASS_ENV", "TEST").upper()
    return "AWM-prod" if env == "PROD" else "AWM-test"


@dataclass
class ExtractionRequest:
    loan_number: str
    client_id: Optional[str] = None
    document_types: List[str] = field(default_factory=list)
    environment: Optional[str] = None
    selection_mode: str = "All"
    use_cache: bool = True
    max_retries: int = 0
    retry_interval_seconds: int = 30
    override_not_found: bool = True

    def __post_init__(self):
        if self.client_id is None:
            self.client_id = _get_default_client_id()
        if self.environment is None:
            if "-prod" in self.client_id.lower():
                self.environment = "prod"
            elif "-test" in self.client_id.lower():
                self.environment = "test"
            else:
                self.environment = "test"


@dataclass
class ExtractionResult:
    success: bool
    all_completed: bool
    documents: List[Dict[str, Any]]
    pending: List[str]
    failed: List[str]
    summary: Dict[str, Any]
    loan_id: str = ""
    loan_number: str = ""
    raw_response: Optional[Dict[str, Any]] = None


class EfolderClient:
    """Client for the EfolderConnect Direct Process API."""

    def __init__(
        self,
        api_url: str = API_BASE_URL,
        token: str = API_TOKEN,
        timeout: int = 60,
    ):
        self.api_url = api_url.rstrip('/')
        self.token = token
        self.timeout = timeout

    def extract_documents(self, request: ExtractionRequest) -> ExtractionResult:
        all_documents = {}
        pending_types = set(request.document_types)
        failed_types = set()
        loan_id = ""
        loan_number = request.loan_number

        response = self._call_api(
            loan_number=request.loan_number,
            client_id=request.client_id,
            document_types=list(pending_types),
            environment=request.environment,
            selection_mode=request.selection_mode,
            use_cache=request.use_cache,
            override_not_found=request.override_not_found,
        )

        if not response.get('success'):
            return ExtractionResult(
                success=False,
                all_completed=False,
                documents=[],
                pending=list(pending_types),
                failed=[],
                summary={'error': response.get('error', 'API call failed')},
                raw_response=response,
            )

        body = response.get('body', {})
        status = response.get('status', 0)
        loan_id = body.get('loanId', '')

        self._process_documents(body.get('documents', []), all_documents, pending_types, failed_types)

        if status == 200 or not pending_types:
            return self._build_result(request, all_documents, pending_types, failed_types, loan_id, loan_number)

        for attempt in range(request.max_retries):
            time.sleep(request.retry_interval_seconds)
            get_response = self.get_documents(loan_number, include_fields=True)
            if get_response.get('error'):
                continue
            for doc in get_response.get('documents', []):
                doc_type = doc.get('DocType', '')
                doc_status = doc.get('Status', '')
                if doc_type not in pending_types:
                    continue
                if doc_status in ['completed', 'stored_no_extraction']:
                    all_documents[doc_type] = {
                        'doc_type': doc_type,
                        'status': 'success' if doc_status == 'completed' else doc_status,
                        'source': 'cache',
                        'extracted_fields': doc.get('ExtractedFields', {}),
                        'extracted_fields_count': doc.get('ExtractedFieldsCount', 0),
                        'document_title': doc.get('DocumentTitle', ''),
                        'attachment_id': doc.get('AttachmentID', ''),
                    }
                    pending_types.discard(doc_type)
                elif doc_status == 'not_found':
                    all_documents[doc_type] = {
                        'doc_type': doc_type, 'status': 'not_found',
                        'source': 'cache', 'extracted_fields': {},
                        'error': doc.get('FailureReason', 'Document not found'),
                    }
                    pending_types.discard(doc_type)
                    failed_types.add(doc_type)
                elif doc_status in ['error-dl', 'error-ext', 'error-sch', 'failed']:
                    all_documents[doc_type] = {
                        'doc_type': doc_type, 'status': 'failed',
                        'source': 'cache', 'extracted_fields': {},
                        'error': doc.get('FailureReason', 'Extraction failed'),
                    }
                    pending_types.discard(doc_type)
                    failed_types.add(doc_type)
            if not pending_types:
                break

        if pending_types:
            for doc_type in list(pending_types):
                all_documents[doc_type] = {
                    'doc_type': doc_type, 'status': 'pending',
                    'source': 'timeout', 'extracted_fields': {},
                }

        return self._build_result(request, all_documents, pending_types, failed_types, loan_id, loan_number)

    def _process_documents(self, documents, all_documents, pending_types, failed_types) -> None:
        for doc in documents:
            doc_type = doc.get('doc_type', '')
            doc_status = doc.get('status', '')
            if doc_status in ['success', 'completed', 'stored_no_extraction']:
                all_documents[doc_type] = doc
                pending_types.discard(doc_type)
            elif doc_status == 'not_found':
                all_documents[doc_type] = doc
                pending_types.discard(doc_type)
                failed_types.add(doc_type)
            elif doc_status == 'failed':
                failed_types.add(doc_type)
                pending_types.discard(doc_type)
                all_documents[doc_type] = doc

    def _build_result(self, request, all_documents, pending_types, failed_types, loan_id, loan_number) -> ExtractionResult:
        return ExtractionResult(
            success=True,
            all_completed=len(pending_types) == 0,
            documents=list(all_documents.values()),
            pending=list(pending_types),
            failed=list(failed_types),
            summary={
                'total_requested': len(request.document_types),
                'completed': len([d for d in all_documents.values() if d.get('status') in ['success', 'completed', 'stored_no_extraction']]),
                'not_found': len([d for d in all_documents.values() if d.get('status') == 'not_found']),
                'pending': len(pending_types),
                'failed': len(failed_types),
            },
            loan_id=loan_id,
            loan_number=loan_number,
        )

    def _call_api(self, loan_number, client_id, document_types, environment, selection_mode, use_cache, override_not_found=False) -> Dict[str, Any]:
        url = f"{self.api_url}/efolder/direct"
        payload = {
            'clientId': client_id,
            'environment': environment,
            'selectionMode': selection_mode,
            'useCache': use_cache,
            'useLlm': True,
            'loanNumber': loan_number,
            'documentTypes': document_types,
            'overrideNotFound': override_not_found,
        }
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }
        try:
            req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
            with urlopen(req, timeout=self.timeout) as response:
                response_body = response.read().decode('utf-8')
                return {
                    'status': response.status,
                    'body': json.loads(response_body) if response_body else {},
                    'success': True,
                }
        except HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            parsed_body = json.loads(error_body) if error_body else {}
            return {'status': e.code, 'body': parsed_body, 'success': False, 'error': str(e)}
        except URLError as e:
            return {'status': 0, 'body': {}, 'success': False, 'error': str(e)}
        except Exception as e:
            return {'status': 0, 'body': {}, 'success': False, 'error': str(e)}

    def get_documents(self, loan_number: str, include_fields: bool = True) -> Dict[str, Any]:
        url = f"{self.api_url}/efolder?loanNumber={loan_number}"
        if include_fields:
            url += "&includeFields=true"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }
        try:
            req = Request(url, headers=headers, method='GET')
            with urlopen(req, timeout=self.timeout) as response:
                response_body = response.read().decode('utf-8')
                return json.loads(response_body) if response_body else {}
        except Exception as e:
            return {'error': str(e)}
