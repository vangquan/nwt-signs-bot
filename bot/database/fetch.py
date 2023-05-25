from pathlib import Path
import json
import shlex
from datetime import datetime
from datetime import timedelta
from subprocess import run

from sqlalchemy import select

from bot.logs import get_logger
from bot.utils import dt_now
from bot.utils.browser import browser
from bot.database import session
from bot.database import get
from bot.database.schema import Bible
from bot.database.schema import Edition
from bot.database.schema import Book
from bot.database.schema import Chapter
from bot.database.schema import VideoMarker
from bot.database.schema import Language
from bot.jw import BiblePassage
from bot import exc


logger = get_logger(__name__)


def languages():
    data = browser.open('https://www.jw.org/en/languages/').json()
    wol = browser.open('https://wol.jw.org/en/wol/li/r1/lp-e').soup
    langs = []
    for i, lang in enumerate(data['languages']):
        meps_symbol = lang['langcode'] # other names: code, langcode, wtlocale, data-meps-symbol
        if not get.language(meps_symbol=meps_symbol):
            a = wol.find('a', {'data-meps-symbol': meps_symbol}) or {}
            langs.append(
                Language(
                    meps_symbol=meps_symbol,
                    code=lang['symbol'], # other names: symbol, locale
                    name=lang['name'],
                    vernacular=lang['vernacularName'],
                    script=lang['script'],
                    is_rtl=lang['direction'] == 'rtl',
                    rsconf=a.get('data-rsconf'),
                    lib=a.get('data-lib'),
                    is_sign_language=lang['isSignLanguage'],
                    is_counted=lang['isCounted'],
                    has_web_content=lang['hasWebContent']
                )
            )
    session.add_all(langs)
    session.commit()


def editions():
    data = browser.open("https://www.jw.org/en/library/bible/json/").json()
    edts = []
    for d in data['langs'].values():
        language_meps_symbol = d['lang']['langcode']
        language = get.language(meps_symbol=language_meps_symbol)
        if not language:
            logger.warning(f'language {language_meps_symbol!r} not found')
            continue
        for e in d['editions']:
            if not get.edition(language_code=language.code):
                edts.append(Edition(
                    language_id=language.id,
                    name=e['title'],
                    symbol=e['symbol'],
                    url=e.get('contentAPI')
                ))
    session.add_all(edts)
    session.commit()


def books(language_code: str):
    edition = get.edition(language_code)
    if not edition:
        logger.warning('No books found in because Bible not exists')
        raise exc.EditionNotFound(language_code)
    if edition.url:
        _fetch_books_json(edition)
    else:
        _fetch_books_wol(edition)


def _fetch_books_json(edition: Edition) -> None:
    data = browser.open(edition.url).json()
    bks = []
    for booknum, bookdata in data['editionData']['books'].items():
        book = get.book(language_code=edition.language.code, booknum=booknum, edition_id=edition.id)
        if book:
            continue
        bks.append(Book(
            edition_id=edition.id,
            number=int(booknum),
            name=bookdata.get('standardName'),
            standard_abbreviation=bookdata.get('standardAbbreviation'),
            official_abbreviation=bookdata.get('officialAbbreviation'),
            standard_singular_bookname=bookdata.get('standardSingularBookName'),
            standard_singular_abbreviation=bookdata.get('standardSingularAbbreviation'),
            official_singular_abbreviation=bookdata.get('officialSingularAbbreviation'),
            standard_plural_bookname=bookdata.get('standardPluralBookName'),
            standard_plural_abbreviation=bookdata.get('standardPluralAbbreviation'),
            official_plural_abbreviation=bookdata.get('officialPluralAbbreviation'),
            book_display_title=bookdata.get('bookDisplayTitle'),
            chapter_display_title=bookdata.get('chapterDisplayTitle')
        ))
    session.add_all(bks)
    session.commit()


def _fetch_books_wol(edition: Edition) -> None:
    "https://wol.jw.org/wol/finder?wtlocale=BRS&pub=nwt"
    browser.open(f'https://wol.jw.org/wol/finder?wtlocale={edition.language.meps_symbol}&pub=nwt', translate_url=False)
    books = browser.page.find('ul', class_='books hebrew clearfix').findChildren('li', recursive=False) + \
            browser.page.find('ul', class_='books greek clearfix').findChildren('li', recursive=False)
    bks = []
    for bk in books:
        book = get.book(language_code=edition.language.code, booknum=int(bk.a['data-bookid']), edition_id=edition.id)
        if book:
            continue
        bks.append(Book(
            edition_id=edition.id,
            number=int(bk.a['data-bookid']),
            name=bk.a.find('span', class_="title ellipsized name").text,
            standard_abbreviation=bk.a.find('span', class_="title ellipsized abbreviation").text,
            official_abbreviation=bk.a.find('span', class_="title ellipsized official").text,
            standard_singular_bookname=bk.a.find('span', class_="title ellipsized name").text,
            standard_singular_abbreviation=bk.a.find('span', class_="title ellipsized abbreviation").text,
            official_singular_abbreviation=bk.a.find('span', class_="title ellipsized official").text,
            standard_plural_bookname=bk.a.find('span', class_="title ellipsized name").text,
            standard_plural_abbreviation=bk.a.find('span', class_="title ellipsized abbreviation").text,
            official_plural_abbreviation=bk.a.find('span', class_="title ellipsized official").text,
            book_display_title=bk.a.find('span', class_="title ellipsized name").text,
            chapter_display_title=bk.a.find('span', class_="title ellipsized name").text
        ))
    session.add_all(bks)
    session.commit()


def need_chapter_and_videomarks(book: Book) -> bool:
    _time_ago = dt_now(naive=True) - timedelta(hours=1) # TODO change hours=24
    if book.refreshed and _time_ago < book.refreshed:
        logger.info(f'Too soon to request {book.name} {book.id=}')
        return False
    else:
        return True


def chapters_and_videomarkers(book: Book, all_chapters=True):
    url = BiblePassage(book).url_pubmedia(all_chapters)
    res = browser.open(url, translate_url=False)
    if res.status_code != 200:
        raise exc.PubmediaNotExists
    data = res.json()['files'][book.edition.language.meps_symbol]

    docs = {}
    for ff, items in data.items():
        docs |= dict(map(lambda d: (int(d['track']), d), items)) if ff != '3GP' else {} # best quality

    for chapternumber, doc in docs.items():
        if doc['file']['url'].endswith('.zip'):
            continue
        chapter = get.chapter(chapternumber, book)
        if chapter and chapter.checksum == doc['file']['checksum']:
            continue
        elif chapter:
            logger.info(f'Updating {chapter.id=}')
            chapter.checksum = doc['file']['checksum']
            chapter.modified_datetime = datetime.fromisoformat(doc['file']['modifiedDatetime'])
            chapter.url = doc['file']['url']
            session.query(VideoMarker).filter(VideoMarker.chapter_id == chapter.id).delete()
            for file in chapter.files:
                file.is_deprecated = True # TODO verify
            # session.commit()
        else:
            logger.info(f'Creating new chapter {book.name} {chapternumber}')
            chapter = Chapter(
                book_id=book.id,
                number=chapternumber,
                checksum=doc['file']['checksum'],
                modified_datetime=datetime.fromisoformat(doc['file']['modifiedDatetime']),
                url=doc['file']['url'],
            )
            session.add(chapter)
        if doc['markers']:
            # Some sign languages not stored videomarkers in json data api. Must be obtained by ffmpeg url video
            for m in doc['markers']['markers']:
                chapter.video_markers.append(
                    VideoMarker(
                        verse_id=select(Bible.id).where(Bible.book == book.number,
                                                        Bible.chapter == chapternumber,
                                                        Bible.verse == int(m['verseNumber'])).scalar() or 0,
                        versenum=int(m['verseNumber']),
                        label=m['label'],
                        duration=m['duration'],
                        start_time=m['startTime'],
                        end_transition_duration=m['endTransitionDuration'],
                    )
                )
        else:
            logger.warning(f'{book.name} {chapter.number} no videomarkers on datajson api {book.edition.language.code}')
        session.commit()
    book.refreshed = dt_now()
    # session.add()
    session.commit()


def need_ffmpeg(chapter: Chapter) -> bool:
    try:
        vms = get.videomarkers(chapter)
    except exc.IncompleteVideoMarkers:
        return True
    else:
        if vms:
            return False
        return True


def videomarkers_by_ffmpeg(chapter: Chapter):
    """Use this method only if videomarkers not stored on data json api.
    No use for bulk. It's slow and expensive. 
    """
    url = BiblePassage(chapter.book, chapter.number).url_pubmedia(all_chapters=False)
    res = browser.open(url, translate_url=False)
    if res.status_code != 200:
        raise exc.PubmediaNotExists

    url_lq = {}
    for ext, items in res.json()['files'][chapter.book.edition.language.meps_symbol].items():
        # low quality urls with markers in video
        url_lq |= dict(map(lambda d: (d['track'], d['file']['url']), reversed(items))) if ext != '3GP' else {}

    url = url_lq[chapter.number]
    session.query(VideoMarker).filter(VideoMarker.chapter_id == chapter.id).delete()
    markers = _ffprobe_markers(url)
    for m in markers:
        chapter.video_markers.append(
            VideoMarker(
                versenum=m['verseNumber'],
                verse_id=select(Bible.id).where(Bible.book == chapter.book.number,
                                                Bible.chapter == m['chapterNumber'],
                                                Bible.verse == m['verseNumber']).scalar() or 0,
                label=m['label'],
                duration=m['duration'],
                start_time=m['startTime'],
                end_transition_duration=m['endTransitionDuration'],
            )
        )
    session.commit()


def _ffprobe_markers(videopath: str):
    videopath = Path(videopath)
    logger.info('Getting ffprobe markers. Slow and expensive %s', videopath)
    console = run(
        shlex.split(f'ffprobe -v quiet -show_chapters -print_format json "{videopath}"'),
        capture_output=True,
        check=True
    )
    raw_chapters = json.loads(console.stdout.decode())['chapters']
    json.dump(raw_chapters, open(videopath.stem + '.json', 'w', encoding='utf-8'), indent=4, ensure_ascii=False)
    markers = []
    for rc in raw_chapters:
        try:
            _, chapternum, verses = BiblePassage.parse_citation_regex(rc['tags']['title'])
        except exc.BibleCitationNotFound:
            continue
        if not chapternum or len(verses) != 1:
            continue
        markers.append(dict(
            duration=str(float(rc['end_time']) - float(rc['start_time'])),
            verseNumber=verses[0],
            chapterNumber=chapternum,
            startTime=str(rc['start_time']),
            label=rc['tags']['title'].strip(),
            endTransitionDuration='0',
        ))
    return markers
