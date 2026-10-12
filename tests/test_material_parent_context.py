from types import SimpleNamespace

from proxy.services.chat_evidence_application_service import smeta_portion_context
from tests.test_smeta_portion_context import TEXT


def test_prior_work_identity_reaches_next_portion():
    class Cursors:
        def progress(self, **kwargs):
            return SimpleNamespace(completed=frozenset({'СКС!984'}), passes=1,
                                   artifact_revision_id=None, exhausted=frozenset(),
                                   decisions={'СКС!984': dict(source_row=984, title='Шкаф напольный 42U',
                                                            norm_code='ГЭСНм10-06-037-01', quantity=2, unit='шт')})
    text, plan = smeta_portion_context(TEXT, session_id='s', limit=2, cursors=Cursors())
    assert 'included_in=984' in text
    assert 'ГЭСНм10-06-037-01' in text
    assert 'СКС!984' not in plan['shown']


def test_first_portion_explains_work_kind_before_material_alternatives():
    class Cursors:
        def progress(self, **kwargs):
            return SimpleNamespace(completed=frozenset(), passes=0, decisions={},
                                   artifact_revision_id=None, exhausted=frozenset())
    text, _ = smeta_portion_context(TEXT, session_id='s', limit=2, cursors=Cursors())
    assert 'decision_kind=работа' in text
    assert text.index('decision_kind=работа') < text.index('самостоятельный материал')
    assert 'способ расчёта' in text
