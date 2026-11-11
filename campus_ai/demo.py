"""Illustrative data, never impersonates real AEDB content."""
from __future__ import annotations
from datetime import datetime, timedelta
from .models import AcademicItem


def sample_items() -> list[AcademicItem]:
    today = datetime.now().date()
    return [
        AcademicItem('demo:sql:atividade', 'demo', 'assignment', 'Exercício: consultas SQL',
            'Banco de Dados', 'Praticar SELECT, JOIN, WHERE e GROUP BY. Material fictício para testar o aplicativo.',
            due_iso=(today + timedelta(days=2)).isoformat() + 'T23:59:00', status='pending'),
        AcademicItem('demo:redes:modulo', 'demo', 'material', 'Aula: protocolos de roteamento',
            'Redes de Computadores', 'Introdução a RIP e OSPF. Conteúdo fictício para demonstração.'),
        AcademicItem('demo:estatistica:prova', 'demo', 'assignment', 'Lista de exercícios de estatística',
            'Estatística', 'Resolver média, moda e desvio padrão. Exercício fictício.',
            due_iso=(today + timedelta(days=5)).isoformat() + 'T23:59:00', status='unknown'),
        AcademicItem('demo:gmail:comunicado', 'demo', 'message', 'Mensagem: atualização de calendário',
            'Comunicados', 'Exemplo fictício de aviso por e-mail institucional.')
    ]
