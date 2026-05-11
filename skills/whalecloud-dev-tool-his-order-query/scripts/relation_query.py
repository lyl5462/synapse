import argparse
import requests
import json
import sys

def parse_args():
    parser = argparse.ArgumentParser(description='Topology Relation Query for Historical Orders')
    parser.add_argument('--server_url', required=True, help='图谱接口的服务器地址')
    parser.add_argument('--prod', required=False, help='产品标识')
    parser.add_argument('--query', required=True, help='作为查询起点的目标节点 ID 或 UUID')
    parser.add_argument('--depth', type=int, default=1, help='拓扑图谱展开的深度')
    return parser.parse_args()

def main():
    args = parse_args()
    
    url = f"{args.server_url.rstrip('/')}/dev/iwhalecloud/synapse/his_order_search"
    payload = {
        "type": "relation",
        "query": args.query,
        "depth": args.depth
    }
    if args.prod:
        payload["prod"] = args.prod
        
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except requests.exceptions.RequestException as e:
        print(f"Error querying relation search API: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
