"""Named element styles share the diagram store; applying one copies its values."""
from copy import deepcopy
import json
import time
import uuid

from .documents import DocumentStore, merge, normalize

FIELDS = frozenset(('fill','stroke','ink','font_size','font_weight','align','border','show_label'))


def values(source):
    if not isinstance(source,dict) or not source or set(source)-FIELDS:
        raise ValueError('A style needs appearance properties only; geometry, text and resources stay on each shape.')
    document={'diagram':{'type':'flowchart','nodes':[{'id':'style'}]},'view':{'nodes':{'style':source}}}
    return normalize(document)['view']['nodes']['style']


class StyleStore:
    def __init__(self,data_dir):
        self.documents=DocumentStore(data_dir)

    def _open(self,write=False):
        db=self.documents._open(write)
        if write:
            db.executescript('''CREATE TABLE IF NOT EXISTS diagram_style_heads(id TEXT PRIMARY KEY,head INTEGER NOT NULL,active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS diagram_style_revisions(id TEXT NOT NULL,revision INTEGER NOT NULL,created REAL NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(id,revision));''')
        return db

    def list(self):
        if not self.documents.path.exists():
            return []
        db=self._open()
        try:
            if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='diagram_style_heads'").fetchone():
                return []
            return [self._row(row) for row in db.execute('SELECT r.* FROM diagram_style_revisions r JOIN diagram_style_heads h ON r.id=h.id AND r.revision=h.head WHERE h.active=1 ORDER BY r.created DESC')]
        finally:
            db.close()

    @staticmethod
    def _row(row):
        return {'id':row['id'],'revision':row['revision'],'created_ts':row['created'],**json.loads(row['payload'])}

    def _get(self,db,sid,revision=None):
        head=db.execute('SELECT head,active FROM diagram_style_heads WHERE id=?',(sid,)).fetchone()
        if not head or (revision is None and not head['active']):
            raise LookupError('Unknown reusable style.')
        row=db.execute('SELECT * FROM diagram_style_revisions WHERE id=? AND revision=?',(sid,revision or head['head'])).fetchone()
        if not row:
            raise LookupError('Unknown reusable style revision.')
        return {**self._row(row),'head_revision':head['head'],'active':bool(head['active'])}

    def get(self,sid,revision=None):
        db=self._open()
        try:
            if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='diagram_style_heads'").fetchone():
                raise LookupError('No reusable styles have been saved.')
            return self._get(db,sid,revision)
        finally:db.close()

    def save(self,name,style,*,sid=None,base_revision=None):
        name=name.strip()
        if not name or len(name)>160:
            raise ValueError('Name the reusable style (up to 160 characters).')
        proposed={'name':name,'values':values(style)}
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            if sid is None:
                sid=uuid.uuid4().hex[:12];revision=1
                db.execute('INSERT INTO diagram_style_heads VALUES(?,?,1)',(sid,revision))
            else:
                if base_revision is None:
                    raise ValueError('Read the style revision before editing it.')
                base=self._get(db,sid,base_revision)
                current=self._get(db,sid,base['head_revision'])
                proposed=merge({k:base[k] for k in ('name','values')},proposed,{k:current[k] for k in ('name','values')})
                revision=current['head_revision']+1
            db.execute('INSERT INTO diagram_style_revisions VALUES(?,?,?,?)',(sid,revision,time.time(),json.dumps(proposed,ensure_ascii=False)))
            db.execute('UPDATE diagram_style_heads SET head=?,active=1 WHERE id=?',(revision,sid))
            result=self._get(db,sid);db.commit();return result
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def remove(self,sid,base_revision):
        db=self._open(True)
        try:
            db.execute('BEGIN IMMEDIATE')
            current=self._get(db,sid,base_revision)
            if current['head_revision']!=base_revision:
                raise ValueError('The reusable style changed; read it before removing it.')
            db.execute('UPDATE diagram_style_heads SET active=0 WHERE id=?',(sid,))
            db.commit();return {'id':sid,'removed':True,'retained_revision':base_revision}
        except BaseException:
            db.rollback();raise
        finally:db.close()


def apply(content,node_ids,style):
    result=deepcopy(content)
    props=values(style)
    ids=set(node_ids)
    if not ids or not ids.issubset({node['id'] for node in content['diagram']['nodes']}):
        raise ValueError('Choose existing shapes to apply the style.')
    for nid in ids:
        result['view']['nodes'][nid]={**result['view']['nodes'].get(nid,{}),**props}
    return result
