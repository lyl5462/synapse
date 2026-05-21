#!/usr/bin/env python3
"""
question-transform.py — 问题格式转换工具

将命令行参数转换为前端可渲染的 JSON 格式问题

用法：
  # 生成单个问题并追加到记录文件（不写 stdout，仅写入 .questions.json）
  py question-transform.py --type=single --title="问题标题" --context="问题描述" --option1="选项A" --option2="选项B" --custom=true

  # 指定输出目录
  py question-transform.py --output_dir=./docs --type=single --title="问题标题" --context="问题描述" --option1="选项A" --option2="选项B"

  # 读取未解决问题并以 JSON 输出到 stdout（仅此与 --readall 会输出问题相关格式化内容）
  py question-transform.py --read

  # 列出全部问题（人类可读文本）到 stdout
  py question-transform.py --readall

  # 指定输出目录读取
  py question-transform.py --read --output_dir=./docs

  # 清空记录文件
  py question-transform.py --reset
"""

import sys
import json
import os

DEFAULT_RECORD_FILE = '.questions.json'

def get_record_file(output_dir=''):
    if output_dir:
        return os.path.join(output_dir, DEFAULT_RECORD_FILE)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), DEFAULT_RECORD_FILE)

def load_record(output_dir=''):
    RECORD_FILE = get_record_file(output_dir)
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"type": "questionnaire", "version": "1.0", "questions": []}

def save_record(data, output_dir=''):
    RECORD_FILE = get_record_file(output_dir)
    os.makedirs(os.path.dirname(RECORD_FILE), exist_ok=True)
    with open(RECORD_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_args(argv):
    out = {
        'type': 'single',
        'title': '',
        'context': '',
        'options': [],
        'custom': True,
        'reset': False,
        'read': False,
        'readall': False,
        'update': False,
        'answer': '',
        'output_dir': ''
    }
    
    i = 1
    while i < len(argv):
        arg = argv[i]
        
        if arg == '--':
            i += 1
            continue
            
        if not arg.startswith('--'):
            sys.stderr.write(f"错误：未知参数 {arg}\n")
            sys.exit(1)
        
        if '=' in arg:
            key, value = arg[2:].split('=', 1)
        else:
            if i + 1 >= len(argv) or argv[i + 1].startswith('--'):
                if arg[2:] == 'reset':
                    out['reset'] = True
                    i += 1
                    continue
                elif arg[2:] == 'read':
                    out['read'] = True
                    i += 1
                    continue
                elif arg[2:] == 'readall':
                    out['readall'] = True
                    i += 1
                    continue
                elif arg[2:] == 'update':
                    out['update'] = True
                    i += 1
                    continue
                else:
                    sys.stderr.write(f"错误：参数 {arg} 缺少值\n")
                    sys.exit(1)
            key = arg[2:]
            value = argv[i + 1]
            i += 1
        
        if key == 'type':
            out['type'] = value if value in ('single', 'multiple', 'boolean') else 'single'
        elif key == 'title':
            out['title'] = value
        elif key == 'context':
            out['context'] = value
        elif key == 'custom':
            out['custom'] = value.lower() == 'true'
        elif key.startswith('option'):
            out['options'].append(value)
        elif key == 'answer':
            out['answer'] = value
        elif key == 'output_dir':
            out['output_dir'] = value
        else:
            sys.stderr.write(f"错误：未知参数 --{key}\n")
            sys.exit(1)
        
        i += 1
    
    return out

def build_question(args, output_dir=''):
    question_type = 'single' if args['type'] == 'boolean' else args['type']
    
    if args['type'] == 'multiple':
        option_style = 'checkbox'
    elif args['type'] == 'boolean':
        option_style = 'boolean'
    else:
        option_style = 'radio'
    
    options = []
    if args['type'] == 'boolean':
        options = [
            {"value": "true", "label": "是", "selected": False},
            {"value": "false", "label": "否", "selected": False}
        ]
    else:
        for i, opt in enumerate(args['options']):
            options.append({
                "value": chr(65 + i),
                "label": opt,
                "selected": False
            })
    
    return {
        "id": f"q{len(load_record(output_dir)['questions']) + 1}",
        "type": question_type,
        "title": args['title'],
        "context": args['context'] or "",
        "options": options,
        "inputEnabled": args['custom'],
        "inputPlaceholder": "或者你的答案：" if args['custom'] else "",
        "required": False,
        "render": {
            "layout": "vertical",
            "optionStyle": option_style,
            "showProgress": True,
            "progress": {"current": 1, "total": 1}
        }
    }

def main():
    args = parse_args(sys.argv)
    output_dir = args['output_dir']
    RECORD_FILE = get_record_file(output_dir)
    
    if args['reset']:
        if os.path.exists(RECORD_FILE):
            os.remove(RECORD_FILE)
        sys.stdout.write("记录文件已清空\n")
        return
    
    if args['read']:
        data = load_record(output_dir)
        unanswered = [q for q in data['questions'] if not q.get('resolved', False)]
        data['questions'] = unanswered
        total = len(unanswered)
        for q in data['questions']:
            q['render']['progress'] = {"current": data['questions'].index(q) + 1, "total": total}
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        sys.stdout.write('\n')
        return
    
    if args['readall']:
        data = load_record(output_dir)
        if not data['questions']:
            sys.stdout.write("记录文件中没有问题\n")
            return
        
        for idx, q in enumerate(data['questions'], 1):
            status = "已解决" if q.get('resolved', False) else "未解决"
            answer = q.get('answer', '')
            answer_line = f" 用户回复：{answer}" if answer else ""
            sys.stdout.write(f"问题{idx}：{q['title']} 内容：{q['context']} 状态：{status}{answer_line}\n")
        return
    
    if args['update']:
        if not args['title']:
            sys.stderr.write('错误：--update 需要 --title 参数\n')
            sys.exit(1)
        if not args['answer']:
            sys.stderr.write('错误：--update 需要 --answer 参数\n')
            sys.exit(1)
        
        record = load_record(output_dir)
        found = False
        for q in record['questions']:
            if q['title'] == args['title']:
                q['answer'] = args['answer']
                q['resolved'] = True
                q['render']['progress']['current'] = q['render']['progress']['total']
                found = True
                break
        
        if not found:
            sys.stderr.write(f"错误：未找到标题为 \"{args['title']}\" 的问题\n")
            sys.exit(1)
        
        save_record(record, output_dir)
        return
    
    if not args['title']:
        sys.stderr.write('错误：缺少必填参数 --title\n')
        sys.exit(1)
    
    if args['type'] != 'boolean' and len(args['options']) == 0:
        sys.stderr.write('错误：缺少选项参数 (--option1 --option2 ...)\n')
        sys.exit(1)
    
    record = load_record(output_dir)
    question = build_question(args, output_dir)
    record['questions'].append(question)
    save_record(record, output_dir)

if __name__ == '__main__':
    main()
