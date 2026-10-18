def command(executable,attempt,model,resume_id):
    args=[executable,'--print','--verbose','--output-format','stream-json']
    if resume_id: args += ['--resume',resume_id]
    if model: args += ['--model',model]
    # Native stream's result is validated again locally; raw stream is retained.
    return args


def parse(record):
    t=record.get('type')
    if t=='system' and record.get('subtype')=='init': return dict(kind='session',session_id=record.get('session_id'),model=record.get('model'))
    if t=='result':
        if record.get('is_error') or record.get('subtype')!='success': return dict(kind='error',code=record.get('subtype','unknown'),session_id=record.get('session_id'))
        return dict(kind='complete',session_id=record.get('session_id'),text=record.get('result'),structured=record.get('structured_output'),usage=record.get('usage'),engine_usd=record.get('total_cost_usd'))
    return dict(kind='unknown')
