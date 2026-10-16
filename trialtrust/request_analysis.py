"""Custom requests remain explicit briefs; unsupported tasks never become pottery."""
from pydantic import BaseModel, ConfigDict, Field
from .compiler import compile_stand_in
from .catalog import CATALOG
from .skill_runtime import invoke

class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=2,max_length=1200)
    reviewed: bool = Field(default=False,strict=True)
    use_model: bool = Field(default=False,strict=True)

class ModelBrief(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: str = Field(min_length=2,max_length=500)
    questions: list[str] = Field(max_length=6)
    next_actions: list[str] = Field(min_length=1,max_length=6)

def analyze(body, provider=None):
    if not body.reviewed:
        raise ValueError('请先检查并确认这段文字已去除个人资料')
    compiled = compile_stand_in(body.text)
    def handle(payload,instructions):
        questions = []
        names = {'domain':'希望体验哪种具体服务？','quantity':'有多少人、份、间或台？','fulfillment':'希望怎样体验或交付？','budget_yuan':'总预算是多少元？','combination':'所选方式与场景不匹配，请核对。'}
        for issue in compiled['issues']:
            question=names.get(issue['field'],'请澄清数量单位与当前场景的关系。')
            if question not in questions: questions.append(question)
        result = {'summary':'已分析明确条件，未把未知需求自动替换成示例。', 'questions':questions,
                  'next_actions':['核对下方已提取条件和未建模内容。','如不能映射到受支持场景，保留需求清单并补充证据，暂不生成试运行结论。'],
                  'mode':'explicit_rules','proposal':compiled['proposal'],'unmodeled_fragments':compiled['unmodeled_fragments'],
                  'field_evidence':compiled['field_evidence'],'can_rehearse':bool(compiled['proposal']),
                  'evidence_needed':['现行价格及全部附加费','退改条款','地点、日期、库存等现实信息需另行核实'],
                  'data_notice':'目录中所有服务价格均为合成演示；自定义分析不核验真实商家、库存或开放时间。'}
        if body.use_model:
            if provider is None: raise ValueError('真实模型尚未启用')
            from .suite import role_json
            brief=role_json(provider,instructions+'\n只做需求梳理，不编造价格、路线、库存、开放时间或已完成动作。不要改变用户条件。',
                            {'request':body.text,'known_fields':compiled['field_evidence'],'unmodeled':compiled['unmodeled_fragments']},ModelBrief)
            result.update(summary=brief.summary,questions=list(dict.fromkeys(questions+brief.questions))[:8],next_actions=brief.next_actions,mode='live_llm')
        return result
    required={'analyze_text'}|({'model_call'} if body.use_model else set())
    result,event=invoke('request-analysis',{'text':body.text},handle,granted=required,required=required)
    return {**result,'skill_events':[event]}
