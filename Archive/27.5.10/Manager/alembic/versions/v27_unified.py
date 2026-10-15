"""V27 unified schema compatibility marker.
Existing databases are upgraded additively by Manager/db.py; this revision is intentionally non-destructive.
"""
revision='v27_unified'; down_revision=None; branch_labels=None; depends_on=None

def upgrade(): pass
def downgrade(): raise RuntimeError('V27 downgrade is disabled.')
