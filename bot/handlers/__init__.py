from .bible import (parse_bible_re_handler, parse_bible_cmd_handler,
                    chapter_handler, verse_handler)
from .settings import showlangs_handler, setlang_handler, quality_handler, pagelang_handler
from .inline_bible import inline_handler
from .misc import (botfather_handler, test_handler, info_inline_handler,
                   all_fallback_handler, notice_handler, logs_handler, logfile_handler)
from .auth import (start_handler, auth_handler, backup_handler,
                   delete_user_handler, getting_user_handler, helper_admin_handler)
from .feedback import feedback_handler

# Order matters
handlers = [
    inline_handler,
    start_handler,
    test_handler,
    showlangs_handler,
    setlang_handler,
    pagelang_handler,
    quality_handler,
    auth_handler,
    feedback_handler,
    info_inline_handler,
    delete_user_handler,
    backup_handler,
    logs_handler,
    logfile_handler,
    notice_handler,
    botfather_handler,
    getting_user_handler,
    helper_admin_handler,
    parse_bible_re_handler,
    parse_bible_cmd_handler,
    chapter_handler,
    verse_handler,
    all_fallback_handler,
]
