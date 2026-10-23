"""Permanent content-addressed provider responses and UTC retrieval observations."""
from __future__ import annotations
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from scripts.ops_storage import atomic_write_files


def retain_response(root: Path, url: str, raw: bytes, *, representation: str = 'bytes', **context) -> dict:
    root=Path(root);digest=hashlib.sha256(raw).hexdigest();path=root/(digest+'.gz')
    if path.exists():
        if gzip.decompress(path.read_bytes())!=raw:raise ValueError('Retained provider response hash mismatch.')
    else:
        atomic_write_files({path:gzip.compress(raw,mtime=0)})
        if gzip.decompress(path.read_bytes())!=raw:raise ValueError('Provider response retention verification failed.')
    observation={**context,'observed_at':datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                 'source_url':url,'sha256':digest,'file':path.name,'representation':representation,'decoded_bytes':len(raw)}
    with (root/'observations.jsonl').open('a',encoding='utf-8') as handle:
        handle.write(json.dumps(observation,ensure_ascii=False,sort_keys=True)+'\n')
        handle.flush()
    return observation
