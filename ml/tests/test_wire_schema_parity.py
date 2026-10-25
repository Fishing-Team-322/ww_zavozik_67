"""Prevent silent drops when a checked-in generated schema lags its proto source."""
from pathlib import Path
import subprocess
import sys

from google.protobuf import descriptor_pb2
from forecast.v1 import forecaster_pb2
from categorize.v3 import discovery_pb2


def test_generated_forecast_and_discovery_match_source_wire_fields(tmp_path):
    root=Path(__file__).resolve().parents[2];output=tmp_path/'schema.pb'
    subprocess.run([sys.executable,'-m','grpc_tools.protoc','-I',str(root/'proto'),
        '--descriptor_set_out='+str(output),str(root/'proto/forecast/v1/forecaster.proto'),
        str(root/'proto/categorize/v3/discovery.proto')],check=True)
    source=descriptor_pb2.FileDescriptorSet.FromString(output.read_bytes())
    by_name={f.name:f for f in source.file}
    def wire(file):
        return {m.name:[(f.name,f.number,f.type,f.label,f.type_name,f.proto3_optional) for f in m.field] for m in file.message_type}
    for descriptor in [forecaster_pb2.DESCRIPTOR,discovery_pb2.DESCRIPTOR]:
        generated=descriptor_pb2.FileDescriptorProto();descriptor.CopyToProto(generated)
        assert wire(generated)==wire(by_name[descriptor.name]),'Generated schema is stale; regenerate before deploying'
