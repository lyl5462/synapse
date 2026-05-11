import argparse
import requests
import json
import sys

def parse_args():
    parser = argparse.ArgumentParser(description='Cypher Query for Historical Orders Graph')
    parser.add_argument('--server_url', required=True, help='图谱接口的服务器地址')
    parser.add_argument('--prod', required=False, help='产品标识')
    parser.add_argument('--query', required=True, help='需要执行的完整 Cypher 查询语句')
    parser.add_argument('--parameters', required=False, help='传递给 Cypher 语句的参数变量 (JSON字符串格式)')
    return parser.parse_args()

def main():
    args = parse_args()
    
    url = f"{args.server_url.rstrip('/')}/dev/iwhalecloud/synapse/his_order_search"
    payload = {
        "type": "cypher",
        "query": args.query
    }
    
    if args.prod:
        payload["prod"] = args.prod
        
    if args.parameters:
        try:
            payload["parameters"] = json.loads(args.parameters)
        except json.JSONDecodeError:
            print("Error: --parameters must be a valid JSON string", file=sys.stderr)
            sys.exit(1)
        
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except requests.exceptions.RequestException as e:
        print(f"Error querying cypher search API: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
