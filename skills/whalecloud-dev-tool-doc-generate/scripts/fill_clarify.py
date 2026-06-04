# -*- coding: utf-8 -*-
"""需求澄清.md 模板填充脚本 v3（修复repl_unclear accum）"""
import json, re, datetime

def fill(template_path, ctx_path, out_path):
    with open(template_path, encoding="utf-8") as f:
        tmpl = f.read()
    with open(ctx_path, encoding="utf-8") as f:
        ctx = json.load(f)

    ts = ctx.get("TIMESTAMP", datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    def g(k, d="[待补充]"): return ctx.get(k, d)

    unclear = ctx.get("unclear", [])
    dialogue = ctx.get("dialogue", [])
    conclusions = ctx.get("conclusions", [])
    scenarios = ctx.get("scenarios", [])
    ac = ctx.get("acceptance_criteria", [])
    fp = ctx.get("feature_points", [])

    result = tmpl
    result = result.replace("{{TIMESTAMP}}", ts)
    result = result.replace("{{REQUIREMENT_NAME}}", g("REQUIREMENT_NAME"))
    result = result.replace("{{STATUS}}", g("STATUS","draft"))
    result = result.replace("{{DEMAND_DESC}}", g("DEMAND_DESC"))
    result = result.replace("{{BACKGROUND}}", g("BACKGROUND"))
    result = result.replace("{{trigger_scenario}}", g("trigger_scenario"))
    result = result.replace("{{pain_point}}", g("pain_point"))
    result = result.replace("{{expected_benefit}}", g("expected_benefit"))
    result = result.replace("{{scope_in}}", g("scope_in"))
    result = result.replace("{{scope_out}}", g("scope_out"))
    result = result.replace("{{tech_constraint}}", g("tech_constraint"))
    result = result.replace("{{module_dependency}}", g("module_dependency"))
    result = result.replace("{{data_dependency}}", g("data_dependency"))

    # {{#each unclear}}
    def repl_unclear(m):
        block = m.group(1)
        if not unclear: return "（无）"
        # find nested {{#if sub_questions}} and {{#each sub_questions}}
        sq_if_m = re.search(r"\{\{#if sub_questions\}\}(.*?)\{\{/if\}\}", block, re.DOTALL)
        sq_each_m = re.search(r"\{\{#each sub_questions\}\}(.*?)\{\{/each\}\}", sq_if_m.group(1), re.DOTALL) if sq_if_m else None
        sq_line_tpl = sq_each_m.group(1) if sq_each_m else ""
        rows = []
        for idx, item in enumerate(unclear, 1):
            d = item if isinstance(item, dict) else {"question": str(item)}
            q = d.get("question",""); title = d.get("title","")
            context = d.get("context",""); ref = d.get("ref","")
            state = d.get("state",""); answer_org = d.get("answer_org",""); answer = d.get("answer","")
            sub_qs = d.get("sub_questions", [])
            sub_block = ""
            if sub_qs and sq_line_tpl:
                sq_filled = []
                for sq in sub_qs:
                    line = sq_line_tpl
                    for k2 in ["question","answer","state"]:
                        line = line.replace("{{"+k2+"}}", sq.get(k2,""))
                    sq_filled.append(line)
                sub_block = sq_each_m.group(0).replace(sq_each_m.group(1), "\n".join(sq_filled))
            elif sub_qs:
                sq_lines = [f"- {sq.get('question','')} → {sq.get('answer','')} [{sq.get('state','')}" for sq in sub_qs]
                sub_block = "#### 追问\n" + "\n".join(sq_lines) + "\n"
            rows.append(f"### 问题 {idx}: {q}\n\n| 字段 | 内容 |\n|------|------|\n| 标题 | {title} |\n| 内容 | {context} |\n| 来源 | {ref} |\n| 状态 | {state} |\n| 用户回答 | {answer_org} |\n| 理解总结 | {answer} |\n{sub_block}\n---")
        return "\n".join(rows)
    result = re.sub(r"\{\{#each unclear\}\}(.*?)\{\{/each\}\}", repl_unclear, result, flags=re.DOTALL)

    # {{#each dialogue}}
    def repl_d(m):
        inner = m.group(1); rows = []
        for idx, row in enumerate(dialogue, 1):
            line = inner.replace("{{@index}}", str(idx))
            for k in ["question_title","type","options","user_answer"]:
                line = line.replace("{{"+k+"}}", row.get(k,"") if isinstance(row,dict) else "")
            rows.append(line)
        return "\n".join(rows) if rows else "| # | 问题 | 类型 | 选项 | 用户回答 |\n|---|------|------|------|----------|"
    result = re.sub(r"\{\{#each dialogue\}\}(.*?)\{\{/each\}\}", repl_d, result, flags=re.DOTALL)

    # {{#each conclusions}}
    def repl_c(m):
        lines = [f"- **{x.get('title','')}**：{x.get('summary','')}" for x in (conclusions or [])]
        return "\n".join(lines) if lines else "（无）"
    result = re.sub(r"\{\{#each conclusions\}\}(.*?)\{\{/each}\}", repl_c, result, flags=re.DOTALL)

    # {{#each scenarios}}
    def repl_s(m):
        rows = []
        for idx, item in enumerate(scenarios or [], 1):
            d = item if isinstance(item,dict) else {"title":str(item)}
            rows.append(f"#### 场景 {idx}: {d.get('title','')}\n\n```gherkin\nFeature: {d.get('feature','')}\n  Scenario: {d.get('title','')}\n    Given {d.get('given','')}\n    When {d.get('when','')}\n    Then {d.get('then','')}\n```\n\n| 字段 | 内容 |\n|------|------|\n| 业务规则 | {d.get('rule','')} |\n| 视角 | {d.get('perspective','')} |\n| 来源 | {d.get('ref','')} |\n| 边缘情况 | {d.get('edge_cases','')} |\n")
        return "\n".join(rows) if rows else "（无）"
    result = re.sub(r"\{\{#each scenarios\}\}(.*?)\{\{/each}\}", repl_s, result, flags=re.DOTALL)

    # {{#each acceptance_criteria}}
    def repl_ac(m):
        lines = [f"- [ ] {x.get('criterion','') if isinstance(x,dict) else str(x)}" for x in (ac or [])]
        return "\n".join(lines) if lines else "（无）"
    result = re.sub(r"\{\{#each acceptance_criteria\}\}(.*?)\{\{/each\}\}", repl_ac, result, flags=re.DOTALL)

    # {{#each feature_points}}
    def repl_fp(m):
        lines = [f"- {x.get('point','') if isinstance(x,dict) else str(x)}" for x in (fp or [])]
        return "\n".join(lines) if lines else "（无）"
    result = re.sub(r"\{\{#each feature_points\}\}(.*?)\{\{/each\}\}", repl_fp, result, flags=re.DOTALL)

    # Cleanup stray HBS
    result = re.sub(r"\{\{/if\}\}", "", result)
    result = re.sub(r"\{\{/each\}\}", "", result)
    result = re.sub(r"\{\{[^}]+\}\}", "", result)

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(result)
    print(f"[OK] Written: {out_path}")

if __name__ == "__main__":
    import sys
    fill(sys.argv[1], sys.argv[2], sys.argv[3])