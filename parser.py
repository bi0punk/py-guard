import json
import os
import re
import uuid
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


ACCESS_PATTERNS = [
    # Common / combined log format (nginx, gunicorn access logs, Apache-style)
    re.compile(
        r'^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+[^\s]+\s+[^\s]+\s+\[(?P<ts>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>[^\s]+)\s+HTTP/[0-9.]+"\s+(?P<status>\d{3})\s+(?P<size>\S+)',
        re.IGNORECASE,
    ),
    # Uvicorn-like access log (useful if Flask/Django app is fronted differently)
    re.compile(
        r'^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?\s*-\s*"(?P<method>[A-Z]+)\s+(?P<path>[^\s]+)\s+HTTP/[0-9.]+"\s+(?P<status>\d{3})',
        re.IGNORECASE,
    ),
    # Django development server log
    re.compile(
        r'^\[(?P<ts>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>[^\s]+)\s+HTTP/[0-9.]+"\s+(?P<status>\d{3})\s+(?P<size>\d+)',
        re.IGNORECASE,
    ),
]

TRACEBACK_START_RE = re.compile(r'^Traceback \(most recent call last\):')
LOG_LEVEL_RE = re.compile(r'\b(ERROR|CRITICAL|FATAL|EXCEPTION)\b', re.IGNORECASE)
INTERNAL_SERVER_ERROR_RE = re.compile(r'Internal Server Error:\s+(?P<path>/\S*)', re.IGNORECASE)
TIMESTAMP_PATTERNS = [
    '%d/%b/%Y:%H:%M:%S %z',  # 09/Apr/2026:10:15:03 +0000
    '%Y-%m-%d %H:%M:%S,%f',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S',
    '%d/%b/%Y %H:%M:%S',
    '%d/%b/%Y %H:%M:%S %z',
    '%d/%b/%Y %H:%M:%S,%f',
    '%d/%b/%Y %H:%M:%S.%f',
    '%d/%b/%Y %H:%M',
    '%d/%b/%Y %H:%M:%S %p',
    '%d/%b/%Y %I:%M:%S %p',
    '%d/%m/%Y %H:%M:%S',
    '%d/%m/%Y %H:%M',
    '%d/%b/%Y %H:%M:%S %Z',
    '%Y-%m-%d %H:%M:%S.%f%z',
    '%Y-%m-%d %H:%M:%S%z',
    '%Y-%m-%dT%H:%M:%S.%f%z',
    '%Y-%m-%dT%H:%M:%S%z',
    '%a %b %d %H:%M:%S %Y',
]


@dataclass
class AccessEvent:
    kind: str
    ip: str
    method: str
    path: str
    normalized_path: str
    status: int
    timestamp: Optional[str] = None


@dataclass
class ErrorEvent:
    kind: str
    message: str
    normalized_message: str
    timestamp: Optional[str] = None
    path_hint: Optional[str] = None


class LogAnalyzer:
    def __init__(self) -> None:
        self.access_events: List[AccessEvent] = []
        self.error_events: List[ErrorEvent] = []
        self.total_lines: int = 0
        self.unparsed_lines: int = 0
        self.recent_events: deque = deque(maxlen=120)
        self.raw_files: List[str] = []

    def parse_files(self, filepaths: Iterable[str]) -> Dict[str, Any]:
        for filepath in filepaths:
            self.raw_files.append(os.path.basename(filepath))
            self._parse_file(filepath)
        return self.build_summary()

    def _parse_file(self, filepath: str) -> None:
        traceback_buffer: List[str] = []
        collecting_traceback = False

        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            for raw_line in fh:
                self.total_lines += 1
                line = raw_line.rstrip('\n')

                if collecting_traceback:
                    if self._is_new_record(line):
                        self._flush_traceback(traceback_buffer)
                        traceback_buffer = []
                        collecting_traceback = False
                    else:
                        traceback_buffer.append(line)
                        continue

                access_event = self._parse_access_line(line)
                if access_event:
                    self.access_events.append(access_event)
                    self.recent_events.append(asdict(access_event))
                    continue

                if TRACEBACK_START_RE.search(line):
                    collecting_traceback = True
                    traceback_buffer = [line]
                    continue

                error_event = self._parse_error_line(line)
                if error_event:
                    self.error_events.append(error_event)
                    self.recent_events.append(asdict(error_event))
                else:
                    self.unparsed_lines += 1

        if collecting_traceback and traceback_buffer:
            self._flush_traceback(traceback_buffer)

    def _flush_traceback(self, traceback_buffer: List[str]) -> None:
        if not traceback_buffer:
            return
        lines = [ln for ln in traceback_buffer if ln.strip()]
        if not lines:
            return
        final_message = lines[-1].strip()
        normalized_message = self.normalize_error_message(final_message)
        event = ErrorEvent(
            kind='error',
            message=' | '.join(lines[-8:]),
            normalized_message=normalized_message,
            timestamp=None,
            path_hint=None,
        )
        self.error_events.append(event)
        self.recent_events.append(asdict(event))

    def _is_new_record(self, line: str) -> bool:
        if not line.strip():
            return True
        if self._parse_access_line(line) is not None:
            return True
        if LOG_LEVEL_RE.search(line):
            return True
        if TRACEBACK_START_RE.search(line):
            return True
        return False

    def _parse_access_line(self, line: str) -> Optional[AccessEvent]:
        for pattern in ACCESS_PATTERNS:
            match = pattern.search(line)
            if match:
                method = (match.groupdict().get('method') or 'UNKNOWN').upper()
                path = match.groupdict().get('path') or '/'
                status_str = match.groupdict().get('status') or '0'
                ip = match.groupdict().get('ip') or 'N/A'
                ts = self.parse_timestamp(match.groupdict().get('ts'))
                return AccessEvent(
                    kind='access',
                    ip=ip,
                    method=method,
                    path=path,
                    normalized_path=self.normalize_path(path),
                    status=int(status_str),
                    timestamp=ts,
                )
        return None

    def _parse_error_line(self, line: str) -> Optional[ErrorEvent]:
        if not line.strip():
            return None

        if LOG_LEVEL_RE.search(line) or 'Internal Server Error' in line or 'Exception:' in line:
            path_hint = None
            m = INTERNAL_SERVER_ERROR_RE.search(line)
            if m:
                path_hint = m.group('path')

            timestamp = self._extract_best_effort_timestamp(line)
            normalized = self.normalize_error_message(line)
            return ErrorEvent(
                kind='error',
                message=line.strip(),
                normalized_message=normalized,
                timestamp=timestamp,
                path_hint=path_hint,
            )
        return None

    def _extract_best_effort_timestamp(self, line: str) -> Optional[str]:
        candidates = re.findall(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[+-]\d{2}:?\d{2})?', line)
        for candidate in candidates:
            ts = self.parse_timestamp(candidate)
            if ts:
                return ts

        bracket_match = re.search(r'\[(.*?)\]', line)
        if bracket_match:
            ts = self.parse_timestamp(bracket_match.group(1))
            if ts:
                return ts
        return None

    @staticmethod
    def parse_timestamp(raw_ts: Optional[str]) -> Optional[str]:
        if not raw_ts:
            return None
        text = raw_ts.strip()
        for fmt in TIMESTAMP_PATTERNS:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def normalize_path(path: str) -> str:
        path_only = path.split('?', 1)[0]
        path_only = re.sub(r'/[0-9]+(?=/|$)', '/<num>', path_only)
        path_only = re.sub(
            r'/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)',
            '/<uuid>',
            path_only,
        )
        path_only = re.sub(r'/[0-9a-fA-F]{16,}(?=/|$)', '/<hex>', path_only)
        return path_only or '/'

    @staticmethod
    def normalize_error_message(message: str) -> str:
        msg = message.strip()
        msg = re.sub(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', '<ip>', msg)
        msg = re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', '<uuid>', msg)
        msg = re.sub(r'\b\d+\b', '<num>', msg)
        msg = re.sub(r'"[^"]+"', '"<text>"', msg)
        return msg[:250]

    def build_summary(self) -> Dict[str, Any]:
        top_ips = Counter(event.ip for event in self.access_events if event.ip != 'N/A').most_common(15)
        top_paths = Counter(event.normalized_path for event in self.access_events).most_common(15)
        top_methods = Counter(event.method for event in self.access_events).most_common(10)
        top_statuses = Counter(str(event.status) for event in self.access_events).most_common(10)
        top_errors = Counter(event.normalized_message for event in self.error_events).most_common(15)

        paths_with_errors = Counter(
            event.path_hint for event in self.error_events if event.path_hint
        ).most_common(10)

        hourly_activity = self._build_hourly_activity()
        ip_status_matrix = self._build_ip_status_matrix()
        route_status_matrix = self._build_route_status_matrix()

        return {
            'analysis_id': str(uuid.uuid4()),
            'files': self.raw_files,
            'summary': {
                'total_lines': self.total_lines,
                'access_events': len(self.access_events),
                'error_events': len(self.error_events),
                'unparsed_lines': self.unparsed_lines,
                'error_rate_pct': round((len(self.error_events) / max(self.total_lines, 1)) * 100, 2),
            },
            'top_ips': [{'ip': ip, 'count': count} for ip, count in top_ips],
            'top_paths': [{'path': path, 'count': count} for path, count in top_paths],
            'top_methods': [{'method': method, 'count': count} for method, count in top_methods],
            'top_statuses': [{'status': status, 'count': count} for status, count in top_statuses],
            'top_errors': [{'message': msg, 'count': count} for msg, count in top_errors],
            'paths_with_errors': [{'path': path, 'count': count} for path, count in paths_with_errors],
            'hourly_activity': hourly_activity,
            'ip_status_matrix': ip_status_matrix,
            'route_status_matrix': route_status_matrix,
            'recent_events': list(self.recent_events)[-50:],
        }

    def _build_hourly_activity(self) -> List[Dict[str, Any]]:
        buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {'access': 0, 'error': 0})

        for event in self.access_events:
            hour = self._hour_bucket(event.timestamp)
            buckets[hour]['access'] += 1

        for event in self.error_events:
            hour = self._hour_bucket(event.timestamp)
            buckets[hour]['error'] += 1

        return [
            {'hour': hour, 'access': values['access'], 'error': values['error']}
            for hour, values in sorted(buckets.items(), key=lambda x: x[0])
        ]

    @staticmethod
    def _hour_bucket(timestamp: Optional[str]) -> str:
        if not timestamp:
            return 'unknown'
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime('%Y-%m-%d %H:00')
        except ValueError:
            return 'unknown'

    def _build_ip_status_matrix(self) -> List[Dict[str, Any]]:
        counter: Dict[str, Counter] = defaultdict(Counter)
        for event in self.access_events:
            if event.ip != 'N/A':
                counter[event.ip][str(event.status)] += 1

        rows = []
        for ip, status_counter in counter.items():
            total = sum(status_counter.values())
            rows.append({
                'ip': ip,
                'total': total,
                '2xx': sum(v for k, v in status_counter.items() if k.startswith('2')),
                '3xx': sum(v for k, v in status_counter.items() if k.startswith('3')),
                '4xx': sum(v for k, v in status_counter.items() if k.startswith('4')),
                '5xx': sum(v for k, v in status_counter.items() if k.startswith('5')),
            })
        rows.sort(key=lambda item: item['total'], reverse=True)
        return rows[:20]

    def _build_route_status_matrix(self) -> List[Dict[str, Any]]:
        counter: Dict[str, Counter] = defaultdict(Counter)
        for event in self.access_events:
            counter[event.normalized_path][str(event.status)] += 1

        rows = []
        for path, status_counter in counter.items():
            total = sum(status_counter.values())
            rows.append({
                'path': path,
                'total': total,
                '2xx': sum(v for k, v in status_counter.items() if k.startswith('2')),
                '3xx': sum(v for k, v in status_counter.items() if k.startswith('3')),
                '4xx': sum(v for k, v in status_counter.items() if k.startswith('4')),
                '5xx': sum(v for k, v in status_counter.items() if k.startswith('5')),
            })
        rows.sort(key=lambda item: item['total'], reverse=True)
        return rows[:20]


def save_summary(base_dir: str, summary: Dict[str, Any]) -> str:
    os.makedirs(base_dir, exist_ok=True)
    analysis_id = summary['analysis_id']
    out_path = os.path.join(base_dir, f'{analysis_id}.json')
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    return out_path


def load_summary(base_dir: str, analysis_id: str) -> Optional[Dict[str, Any]]:
    target = os.path.join(base_dir, f'{analysis_id}.json')
    if not os.path.exists(target):
        return None
    with open(target, 'r', encoding='utf-8') as fh:
        return json.load(fh)
