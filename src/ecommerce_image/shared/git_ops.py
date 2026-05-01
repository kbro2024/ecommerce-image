"""
Git Operations for ecommerce-image workflow
"""
import subprocess
import os
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(os.environ.get('ECOMMERCE_IMAGE_REPO', '/home/admin/ecommerce-image'))

def run_git(*args, cwd=None):
    """Execute git command"""
    result = subprocess.run(
        ['git'] + list(args),
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git error: {result.stderr}")
    return result.stdout.strip()

def init_repo():
    """Initialize git repo if not exists"""
    if not (REPO_ROOT / '.git').exists():
        run_git('init')
        run_git('config', 'user.email', 'hermes@ecommerce.image')
        run_git('config', 'user.name', 'Hermes Agent')
        # Create directory structure
        for d in ['inbox', 'output', 'approved', 'rejected', 'briefs']:
            (REPO_ROOT / d).mkdir(parents=True, exist_ok=True)
        # Initial commit
        run_git('add', '.')
        run_git('commit', '-m', 'chore: initialize ecommerce-image repo')
    return REPO_ROOT

def add(path):
    """Stage files"""
    run_git('add', str(path))

def commit(message, cwd=None):
    """Commit with message"""
    run_git('commit', '-m', message, cwd=cwd)

def tag(tag_name, ref=None):
    """Create tag"""
    cmd = ['tag', tag_name]
    if ref:
        cmd.append(ref)
    run_git(*cmd)

def diff(path=None):
    """Get diff of staged/unstaged changes"""
    cmd = ['diff', '--name-only']
    if path:
        cmd.append(str(path))
    return run_git(*cmd)

def log(path=None, max_count=10):
    """Get commit log"""
    cmd = ['log', f'--oneline', f'-n{max_count}']
    if path:
        cmd.append('--')
        cmd.append(str(path))
    return run_git(*cmd)

def show(ref, path=None):
    """Show commit or file at ref"""
    cmd = ['show', ref]
    if path:
        cmd.append('--')
        cmd.append(str(path))
    return run_git(*cmd)

def branch(name):
    """Create branch"""
    run_git('checkout', '-b', name)

def checkout(ref):
    """Checkout ref"""
    run_git('checkout', ref)

def move(src, dst):
    """Move file/directory"""
    run_git('mv', str(src), str(dst))

def copy(src, dst):
    """Copy file (git add + commit)"""
    import shutil
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if src.endswith('/'):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)

def get_uncommitted():
    """Get list of uncommitted changes"""
    diff_output = run_git('diff', '--name-only')
    staged = run_git('diff', '--cached', '--name-only')
    untracked = run_git('ls-files', '--others', '--exclude-standard')
    return {
        'modified': diff_output.split('\n') if diff_output else [],
        'staged': staged.split('\n') if staged else [],
        'untracked': untracked.split('\n') if untracked else []
    }

def auto_rescue_commit():
    """Auto-commit uncommitted changes (exclude inbox/)"""
    changes = get_uncommitted()
    all_changes = []
    for category in ['modified', 'staged', 'untracked']:
        for f in changes[category]:
            if not f.startswith('inbox/') and f:
                all_changes.append(f)
    
    if all_changes:
        run_git('add', '.')
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        run_git('commit', '-m', f'[AUTO-RESCUE] auto save at {ts}')
        return True
    return False
