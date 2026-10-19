"""Set the spike tool's static filter: set_filter.py <env> '<filter>'"""
import os, sys
from dotenv import load_dotenv
load_dotenv(sys.argv[1])
from google.cloud import ces_v1beta
from google.protobuf import field_mask_pb2
P = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
c = ces_v1beta.AgentServiceClient()
name = f"projects/{P}/locations/us/apps/spike-dstool/tools/search-tutorials"
t = c.get_tool(name=name)
t.data_store_tool.data_store_source.filter = sys.argv[2]
c.update_tool(tool=t, update_mask=field_mask_pb2.FieldMask(paths=["data_store_tool.data_store_source.filter"]))
print("filter =", c.get_tool(name=name).data_store_tool.data_store_source.filter)
