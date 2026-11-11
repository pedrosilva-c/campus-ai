"""FICTITIOUS Companion snapshots (campus-ai.academic/1) for persistence and host tests. No real data."""
from campus_ai import contract

ITEMS = [
    ('90001', 'assign', 'Exercício sintético A'),
    ('90002', 'assign', 'Exercício sintético B'),
    ('90003', 'assign', 'Exercício sintético C'),
    ('90004', 'resource', 'AV1 - Gabarito sintético'),
    ('90005', 'assign', 'AV1 - Correção sintética'),
    ('90006', 'groupselect', 'Grupos para trabalho de AV2 (sintético)'),
    ('90007', 'assign', 'Tarefa em grupo sintética'),
]


def snapshot_dict(items=ITEMS, *, course='7653', section='4242', section_name='Atividades Avaliativas',
                  generated='2026-11-05T20:00:00Z', coverage='parcial', source='companion', extra_sections=()):
    course_uid = f'moodle:course:{course}'
    section_uid = f'{course_uid}:section:id-{section}'

    def prov():
        return {'source': source, 'observed_at': generated, 'method': 'dom', 'route': '/ava/course/view.php?id'}

    materials, activities = [], []
    for cmid, kind, title, *rest in items:
        uid = rest[0] if rest else f'{course_uid}:module:{cmid}'
        record = {'uid': uid, 'course_uid': course_uid, 'section_uid': section_uid, 'title': title, 'kind': kind,
                  'url': '', 'provenance': prov(), 'verification': 'confirmado', 'confidence': 'alta',
                  'assessment': '', 'assessment_basis': ''}
        if kind in contract.MATERIAL_KINDS:
            materials.append(record)
        else:
            activities.append({**record, 'deadlines': [], 'submission': 'desconhecido'})
    sections = [{'uid': section_uid, 'course_uid': course_uid, 'name': section_name, 'position': None,
                 'state': 'aberta', 'provenance': prov(), 'verification': 'confirmado', 'confidence': 'alta'}]
    for extra in extra_sections:
        sections.append({**sections[0], 'uid': f'{course_uid}:section:id-{extra}', 'name': f'Seção {extra}'})
    return {
        'schema': contract.SCHEMA_ID, 'generated_at': generated, 'scope': [course_uid],
        'coverage': {'state': coverage, 'reasons': ['Somente esta seção foi lida.']},
        'sources': [{'source': source, 'last_attempt': generated, 'last_success': generated,
                     'status': 'parcial', 'message': ''}],
        'courses': [{'uid': course_uid, 'moodle_id': course, 'name': 'Disciplina fictícia', 'provenance': prov(),
                     'url': f'https://ead.aedb.br/ava/course/view.php?id={course}', 'verification': 'confirmado',
                     'confidence': 'alta'}],
        'sections': sections, 'materials': materials, 'activities': activities, 'events': [], 'announcements': [],
    }


def snapshot(items=ITEMS, **kwargs):
    return contract.parse_snapshot(snapshot_dict(items, **kwargs))
