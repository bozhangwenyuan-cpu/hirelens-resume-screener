from __future__ import annotations

import json
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import app
from model_client import build_screening_prompt, llm_enabled


JOB_PAYLOAD = {
    "title": "B2B 大客户销售经理",
    "headcount": 2,
    "arrival_date": "2026-06-30",
    "status": "在进行",
    "jd_text": "负责工业电子/元器件方向 B2B 客户开发，挖掘重点客户需求，推进方案型销售、报价、合同和回款；维护渠道和代理商关系，协同技术团队完成项目导入。",
    "persona": {
        "age_range": "28-38",
        "gender_preference": "不限",
        "work_years": "5 年以上",
        "min_education": "本科",
        "job_hop_frequency": "近 5 年不超过 2 次",
        "persona_keywords": ["大客户", "方案销售", "抗压", "回款"],
    },
    "must": {
        "years": "3 年以上 B2B 销售经验",
        "industry": "电子元器件、工业品或半导体",
        "skills": "大客户开发、方案销售、合同回款",
        "cert": "不限",
        "other": "能够独立推进销售线索到成交\n可接受华东区域出差",
    },
    "bonus": {
        "resources": "有华东制造业客户资源",
        "tools": "熟悉 CRM",
        "language": "英文邮件沟通",
        "management": "渠道或代理商管理",
        "other": "有技术型产品销售经验",
    },
}


CASES = [
    {
        "name": "strong_match",
        "expected": "非常匹配",
        "candidate_name": "张强",
        "resume_text": "本科，6 年 B2B 销售经验，最近 4 年在电子元器件代理商负责华东区域大客户开发。熟悉制造业客户需求挖掘、方案销售、报价、合同谈判和回款。独立推进过多个传感器和电源模块项目从线索到成交，年销售额 1200 万。熟悉 CRM，有渠道商协同经验，可接受华东出差，能阅读英文产品资料。",
    },
    {
        "name": "medium_match",
        "expected": "一般匹配",
        "candidate_name": "李敏",
        "resume_text": "本科，4 年工业自动化设备销售经验，主要负责区域客户维护和部分新客户开发，参与过方案报价和合同跟进。对电子制造客户有接触，但没有直接做过电子元器件代理销售，回款和渠道管理经验较少。熟悉 CRM，可接受出差。",
    },
    {
        "name": "weak_match",
        "expected": "不匹配",
        "candidate_name": "王磊",
        "resume_text": "2 年门店零售销售经验，主要负责客户接待、商品陈列和日常销售。没有 B2B 大客户开发经验，也没有电子元器件、工业品或半导体行业经验。希望转型做企业销售。",
    },
    {
        "name": "risk_case",
        "expected": "一般匹配",
        "candidate_name": "赵云",
        "resume_text": "5 年 B2B 销售经验，做过工业品客户开发和方案销售。过去 4 年换过 4 份工作，其中两段经历不足 8 个月。熟悉客户拜访、报价和合同流程，但简历没有说明个人业绩数字和回款责任。",
    },
]


def conclusion_rank(value: str) -> int:
    return {"不匹配": 0, "一般匹配": 1, "非常匹配": 2}.get(value, -1)


def main() -> None:
    app.init_db()
    job = app.save_job(JOB_PAYLOAD)
    results: list[dict[str, Any]] = []
    pass_count = 0

    for case in CASES:
        resume = app.save_resume(case["candidate_name"], f"{case['name']}.txt", case["resume_text"], "eval")
        evaluation = app.evaluate_resume(job, resume)
        ok = evaluation["conclusion"] == case["expected"]
        close = abs(conclusion_rank(evaluation["conclusion"]) - conclusion_rank(case["expected"])) <= 1
        pass_count += 1 if ok else 0
        results.append(
            {
                "case": case["name"],
                "candidate": case["candidate_name"],
                "expected": case["expected"],
                "actual": evaluation["conclusion"],
                "score": evaluation["score"],
                "ok": ok,
                "close": close,
                "model_name": evaluation.get("model_name"),
                "matched_points": evaluation.get("matched_points", [])[:3],
                "missing_points": evaluation.get("missing_points", [])[:3],
                "risk_points": evaluation.get("risk_points", [])[:3],
            }
        )

    sample_prompt = build_screening_prompt(
        job,
        {
            "id": "resume_sample",
            "candidate_name": CASES[0]["candidate_name"],
            "file_name": "sample.txt",
            "parsed_text": CASES[0]["resume_text"],
        },
    )
    report = {
        "llm_enabled": llm_enabled(),
        "pass_count": pass_count,
        "total": len(CASES),
        "accuracy": round(pass_count / len(CASES), 2),
        "results": results,
        "prompt_shape": {
            "task": sample_prompt["task"],
            "has_output_schema": bool(sample_prompt["output_schema"]),
            "has_scoring_guidance": bool(sample_prompt["scoring_guidance"]),
            "job_keys": sorted(sample_prompt["job"].keys()),
            "resume_keys": sorted(sample_prompt["resume"].keys()),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
