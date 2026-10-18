def command(executable,attempt,model,resume_id,stage):
    # exec owns --sandbox; the resume subcommand does not accept it afterward.
    args=[executable,'exec','--sandbox','workspace-write' if stage=='implement' else 'read-only',
          '--config','approval_policy="never"','--ignore-user-config','--ignore-rules']
    if resume_id: args += ['resume',resume_id]
    args += ['--json','--output-last-message',str(attempt/'final.json'),'--output-schema',str(attempt/'response-schema.json')]
    if model: args += ['--model',model]
    return args+['-']


def parse(record):
    t=record.get('type')
    if t=='thread.started': return dict(kind='session',session_id=record.get('thread_id'))
    if t=='turn.completed': return dict(kind='complete',usage=record.get('usage'))
    if t in ('error','turn.failed'): return dict(kind='error',code=t)
    if t=='item.completed' and record.get('item',{}).get('type')=='agent_message': return dict(kind='answer',text=record['item'].get('text'))
    return dict(kind='unknown')
