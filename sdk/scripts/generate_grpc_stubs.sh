#!/usr/bin/env bash
# Regenerate Python gRPC stubs from proto/faultline.proto
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
python -m grpc_tools.protoc \
  -I "$ROOT/proto" \
  --python_out="$ROOT/sdk/faultline/grpc" \
  --grpc_python_out="$ROOT/sdk/faultline/grpc" \
  "$ROOT/proto/faultline.proto"
# Fix relative import in generated grpc module
sed -i 's/import faultline_pb2/from . import faultline_pb2/' "$ROOT/sdk/faultline/grpc/faultline_pb2_grpc.py" 2>/dev/null || \
  python -c "
from pathlib import Path
p = Path('$ROOT/sdk/faultline/grpc/faultline_pb2_grpc.py')
text = p.read_text(encoding='utf-8')
text = text.replace('import faultline_pb2', 'from . import faultline_pb2', 1)
p.write_text(text, encoding='utf-8')
"
