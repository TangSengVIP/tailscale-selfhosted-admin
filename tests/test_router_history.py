"""Enrollment-history display must not merge across access boundaries."""
import ast
import copy
from pathlib import Path
import re
import unittest

source = Path(__file__).resolve().parents[1] / 'src/server.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'coalesce_router_devices')
namespace = {'re': re}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
coalesce = namespace['coalesce_router_devices']


def node(id, **kw):
    return dict(id=id, hostname='AurosaRouter-a1b2c3', user_id=6, admin=False, tags=[],
                created=id*100, online=False, name=kw.pop('name', 'router'),
                has_note=False, **kw)


class HistoryTests(unittest.TestCase):
    def test_refill_note_and_preserve_current_identity(self):
        old=node(1,name='TR3000');old['has_note']=True
        current=node(2);current['online']=True
        before=copy.deepcopy([old,current])
        result=coalesce([old,current])
        self.assertEqual(len(result),1)
        self.assertEqual((result[0]['id'],result[0]['name']),(2,'TR3000'))
        self.assertEqual(result[0]['registration_history'][0]['id'],1)
        self.assertEqual([old,current],before)

    def test_both_offline_remain_grouped(self):
        self.assertEqual(len(coalesce([node(1),node(2)])),1)

    def test_old_online_or_both_online_stay_separate(self):
        for new_online in (False,True):
            a,b=node(1),node(2);a['online']=True;b['online']=new_online
            self.assertEqual(len(coalesce([a,b])),2)

    def test_cross_user_never_merge(self):
        a,b=node(1),node(2);b['user_id']=11
        self.assertEqual(len(coalesce([a,b])),2)

    def test_tags_and_generic_names_never_merge(self):
        for change in ({'tags':['tag:other']},{'admin':True},{'hostname':'localhost'}):
            a,b=node(1),node(2);a.update(change);b.update(change)
            self.assertEqual(len(coalesce([a,b])),2)

    def test_new_note_wins_and_multiple_flashes(self):
        a,b,c=node(1),node(2),node(3)
        a.update(has_note=True,name='old');c.update(has_note=True,name='new')
        result=coalesce([a,b,c]);self.assertEqual(result[0]['name'],'new')
        self.assertEqual(len(result[0]['registration_history']),2)

    def test_empty(self):
        self.assertEqual(coalesce([]),[])


if __name__=='__main__':unittest.main()
