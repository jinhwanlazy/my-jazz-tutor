"""Bounded, reproducible views of the original ledger. No inferred mastery.

Rebuild from current events (including corrections), never summarize a summary.
The request artifact is the private snapshot/cache of this view. Raw history and
MIDI remain in their original stores, outside Git and outside the prompt.
"""
from collections import Counter
import json
import re

from difficulty import prediction_observation, score_features

POLICY = 'bounded-evidence-v1'
RECENT = 8
RELATED = 4


def evidence_ids(context):
    """Quoted old reports are evidence; a bare example ID is only provenance."""
    ids = {source['id'] for source in context['sources']}
    for source in context['sources']:
        if source['id'] == 'history-summary':
            ids.update(quote['source_id'] for quote in source['data'].get('latest_reported_excerpts_per_label_or_skip_reason', []))
    return ids


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode())


def excerpt(value, limit=1200):
    """Exact excerpts with explicit omission, never a fabricated paraphrase."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return {'excerpt': value[:limit], 'omitted_characters': len(value) - limit}


def compact(value, limit=1200):
    if isinstance(value, dict):
        if set(value) == {'excerpt', 'omitted_characters'} and isinstance(value['excerpt'], str):
            text = value['excerpt']
            return {'excerpt': text[:limit], 'omitted_characters': value['omitted_characters'] + max(0,len(text)-limit)}
        return {k: compact(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(v, limit) for v in value[:8]] + ([{'omitted_items': len(value)-8}] if len(value) > 8 else [])
    return excerpt(value, limit)


def state(task):
    import review as r
    return ('pending' if r.is_pending(task) else 'retired' if task['retired'] else
            'discarded' if task['discarded'] else 'cancelled' if task['cancelled'] else 'completed')


def conditions(target):
    e = target.get('exercise')
    if e:
        view = {k: e[k] for k in ('title', 'objective', 'section', 'key', 'bpm', 'bars', 'minutes',
                                  'left_hand', 'right_hand', 'notes', 'rhythm', 'instructions')}
        view['score_features'] = score_features(e)
        view['notation_policy'] = 'Full score remains in the original task snapshot; this is a compact description.'
    else:
        view = {k: target[k] for k in ('title', 'key', 'bpm', 'bars', 'arrangement', 'rhythm', 'bass', 'voicing', 'melody', 'instructions')}
    if target.get('difficulty'):
        d = target['difficulty']
        view['assigned_demand_assessment'] = {
            'kind': 'model_interpretation_at_assignment_not_observed_ability', 'rubric_version': d['rubric_version'],
            'axes': {k: {'level': v['level'], 'status': v['status']} for k, v in d['axes'].items()},
            'focus_axes': d['focus_axes']}
    return compact(view)


def task_sources(task, sessions):
    a = task['assignment']; tid = a['task_id']
    sources = [{'id': 'task:' + tid, 'kind': 'assigned_conditions',
                'data': {'task_id': tid, 'exercise_id': a['exercise_id'], 'assigned_at': a['recorded_at'],
                         'conditions': conditions(task['target']), 'state': state(task)}}]
    for field in ('completion', 'report', 'cancellation'):
        event = task[field]
        if event:
            data = {k: event[k] for k in ('event_id', 'task_id', 'event_type', 'recorded_at', 'practice_date',
                    'difficulty', 'raw_note', 'reason', 'actual_minutes', 'supersedes')}
            for k in ('actual_json', 'checks_json'):
                data[k] = json.loads(event[k]) if event[k] else {}
            if data['reason'].startswith('{'):
                try:
                    data['reason'] = json.loads(data['reason'])
                except ValueError:
                    pass
            sources.append({'id': 'event:' + event['event_id'], 'kind': event['event_type'], 'data': compact(data)})
    measured = [s for s in sessions if s['task_id'] == tid]
    for session in measured[-3:]:
        sources.append({'id': 'session:' + session['id'], 'kind': 'session_measurements_not_performance_analysis',
                        'data': compact({k: session[k] for k in ('id', 'task_id', 'status', 'created_at', 'summary')})})
    if len(measured) > 3:
        sources[0]['data']['omitted_session_summaries'] = len(measured) - 3
    comparison = prediction_observation(task)
    if comparison:
        sources.append({'id': 'comparison:' + tid, 'kind': 'prior_prediction_and_latest_self_report', 'data': comparison})
    return sources


def updated_at(task):
    return max(e['recorded_at'] for e in (task['assignment'], task['report'], task['completion'], task['cancellation']) if e)


def summary(tasks, events):
    labels, statuses, forecasts = Counter(), Counter(), Counter()
    samples, quotes = {}, {}
    # Newest corrections take precedence in samples; totals use latest reports only.
    for task in sorted(tasks, key=updated_at):
        statuses[state(task)] += 1
        report = task['report']
        if report:
            label = report['difficulty'] or 'unlabeled'
            labels[label] += 1
            samples.setdefault(label, []).append('event:' + report['event_id'])
            if report['raw_note']:
                quotes[label] = {'source_id': 'event:' + report['event_id'], 'recorded_at': report['recorded_at'],
                                 'kind': 'user_report', 'label': label, 'text': excerpt(report['raw_note'], 400)}
        if task['discarded']:
            event = task['cancellation']
            reason = json.loads(event['reason'])
            if reason['note']:
                quotes['skip:' + reason['choice']] = {'source_id': 'event:' + event['event_id'],
                    'recorded_at': event['recorded_at'], 'kind': 'user_skip_reason', 'text': excerpt(reason['note'], 400)}
        pair = prediction_observation(task)
        if pair and not pair['reused_prediction']:
            forecasts[pair['rubric_version'] + '/' + pair['predicted_burden_at_assignment'] + '/' + pair['reported_label']] += 1
    return {'id': 'history-summary', 'kind': 'ledger_facts_not_ability_assessment', 'data': {
        'policy': POLICY, 'task_count': len(tasks), 'event_count': len(events),
        'last_event_id': events[-1]['event_id'] if events else None,
        'date_range': [min((t['assignment']['recorded_at'] for t in tasks), default=None),
                       max((updated_at(t) for t in tasks), default=None)],
        'states': dict(statuses), 'latest_feedback_counts': dict(labels),
        'feedback_example_event_ids': {k: v[-2:] for k, v in samples.items()},
        'latest_reported_excerpts_per_label_or_skip_reason': list(quotes.values()),
        'prior_forecast_and_feedback_counts': dict(forecasts),
        'interpretation': 'Counts describe records, not correctness or mastery. Good reports utility, not medium burden. '
                          'Skipped/retired tasks are not failed performances. Exact quoted reports may be cited '
                          'by their source_id, but bare example IDs supply no case detail. Quoted notes alone '
                          'do not establish omitted conditions or performance accuracy.'}}


def select(tasks, request):
    recent = list(reversed(tasks[-RECENT:]))
    recent_ids = {t['assignment']['task_id'] for t in recent}
    older = [t for t in tasks if t['assignment']['task_id'] not in recent_ids]
    # Surface recently corrected older feedback as well as text/condition similarity.
    corrected = sorted([t for t in older if t['report'] and t['report']['event_type'] == 'corrected'], key=updated_at, reverse=True)[:2]
    query = set(re.findall(r'[\w#]+', request.lower()))
    last = tasks[-1]['target'] if tasks else {}
    focus = set(last.get('difficulty', {}).get('focus_axes', []))
    def relevance(task):
        target = task['target']
        note = (task['report'] or {}).get('raw_note', '')
        reason = (task['cancellation'] or {}).get('reason', '')
        text = json.dumps(conditions(target), ensure_ascii=False).lower() + note.lower() + reason.lower()
        matches = sum(word in text for word in query if len(word) > 1)
        overlap = len(focus & set(target.get('difficulty', {}).get('focus_axes', [])))
        return matches * 5 + overlap * 2 + int(target['key'] == last.get('key')), updated_at(task)
    related = []
    for task in corrected + sorted(older, key=relevance, reverse=True):
        if task not in related:
            related.append(task)
        if len(related) == RELATED:
            break
    return recent, related


def fit(context, tasks, sessions, events, budget):
    """Keep current request/rules, a bounded factual rollup and whole source groups.

    UTF-8 bytes are a conservative token upper-bound for the app-supplied text,
    not a claim about the model's hidden protocol overhead or tokenizer count.
    """
    recent, related = select(tasks, context['request'])
    window = context['history_window']
    window.update(policy=POLICY, total_tasks=len(tasks), included_tasks=0, omitted_older_tasks=len(tasks),
                  included_task_ids=[], omitted_detail_tasks=len(tasks),
                  selection='Up to 8 recent and 4 relevant/corrected older tasks; input budget takes precedence.',
                  omissions='Omitted details and clipped text remain in the original local ledger. Absence is not lack of practice.')
    context['sources'].append(summary(tasks, events))
    if encoded_size(context) > budget:
        raise ValueError('The profile, request and required coaching rules exceed the input budget.')
    # Reserve space for accurate coverage counters and byte accounting.
    for task in recent + related:
        group = task_sources(task, sessions)
        if encoded_size(context) + encoded_size(group) + 500 > budget:
            # Keep the source list intact while reducing individual descriptions.
            group = [compact(source, 300) for source in task_sources(task, sessions)]
        if encoded_size(context) + encoded_size(group) + 500 > budget:
            continue
        context['sources'].extend(group)
        window['included_task_ids'].append(task['assignment']['task_id'])
        window['included_tasks'] += 1
    window['omitted_detail_tasks'] = len(tasks) - window['included_tasks']
    selected = set(window['included_task_ids'])
    window['omitted_older_tasks'] = sum(t['assignment']['task_id'] not in selected for t in tasks[:-RECENT])
    # Numeric references in the rollup are provenance, not a license to cite absent events.
    return context
