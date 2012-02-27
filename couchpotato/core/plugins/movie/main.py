from couchpotato import get_session
from couchpotato.api import addApiView
from couchpotato.core.event import fireEvent, fireEventAsync, addEvent
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.request import getParams, jsonified
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.core.settings.model import Movie, Library, LibraryTitle
from couchpotato.environment import Env
from sqlalchemy.orm import joinedload_all
from sqlalchemy.sql.expression import or_, asc, not_
from string import ascii_lowercase
from urllib import urlencode

log = CPLog(__name__)


class MoviePlugin(Plugin):

    default_dict = {
        'profile': {'types': {'quality': {}}},
        'releases': {'status': {}, 'quality': {}, 'files':{}, 'info': {}},
        'library': {'titles': {}, 'files':{}},
        'files': {},
        'status': {}
    }

    def __init__(self):
        addApiView('movie.search', self.search, docs = {
            'desc': 'Search the movie providers for a movie',
            'params': {
                'q': {'desc': 'The (partial) movie name you want to search for'},
            },
            'return': {'type': 'object', 'example': """{
    'success': True,
    'empty': bool, any movies returned or not,
    'movies': array, movies found,
}"""}
        })
        addApiView('movie.list', self.listView, docs = {
            'desc': 'List movies in wanted list',
            'params': {
                'status': {'type': 'array or csv', 'desc': 'Filter movie by status. Example:"active,done"'},
                'limit_offset': {'desc': 'Limit the movie list. Examples: "50", "50,30"'},
                'starts_with': {'desc': 'Starts with these characters. Example: "a" returns all movies starting with the letter "a"'},
                'search': {'desc': 'Search movie title'},
            },
            'return': {'type': 'object', 'example': """{
    'success': True,
    'empty': bool, any movies returned or not,
    'movies': array, movies found,
}"""}
        })
        addApiView('movie.refresh', self.refresh, docs = {
            'desc': 'Refresh a movie by id',
            'params': {
                'id': {'desc': 'The id of the movie that needs to be refreshed'},
            }
        })
        addApiView('movie.available_chars', self.charView)
        addApiView('movie.add', self.addView, docs = {
            'desc': 'Add new movie to the wanted list',
            'params': {
                'identifier': {'desc': 'IMDB id of the movie your want to add.'},
                'profile_id': {'desc': 'ID of quality profile you want the add the movie in. If empty will use the default profile.'},
                'title': {'desc': 'Movie title to use for searches. Has to be one of the titles returned by movie.search.'},
            }
        })
        addApiView('movie.edit', self.edit, docs = {
            'desc': 'Add new movie to the wanted list',
            'params': {
                'id': {'desc': 'Movie ID(s) you want to edit.', 'type': 'int (comma separated)'},
                'profile_id': {'desc': 'ID of quality profile you want the edit the movie to.'},
                'default_title': {'desc': 'Movie title to use for searches. Has to be one of the titles returned by movie.search.'},
            }
        })
        addApiView('movie.delete', self.delete, docs = {
            'desc': 'Delete a movie from the wanted list',
            'params': {
                'id': {'desc': 'Movie ID(s) you want to delete.', 'type': 'int (comma separated)'},
            }
        })

        addEvent('movie.add', self.add)
        addEvent('movie.get', self.get)
        addEvent('movie.list', self.list)
        addEvent('movie.restatus', self.restatus)

    def get(self, movie_id):

        db = get_session()
        m = db.query(Movie).filter_by(id = movie_id).first()

        return m.to_dict(self.default_dict)

    def list(self, status = ['active'], limit_offset = None, starts_with = None, search = None):

        db = get_session()

        # Make a list from string
        if not isinstance(status, (list, tuple)):
            status = [status]


        q = db.query(Movie) \
            .join(Movie.library, Library.titles) \
            .options(joinedload_all('library.titles')) \
            .options(joinedload_all('library.files')) \
            .options(joinedload_all('status')) \
            .options(joinedload_all('files')) \
            .filter(LibraryTitle.default == True) \
            .filter(or_(*[Movie.status.has(identifier = s) for s in status]))

        filter_or = []
        if starts_with:
            starts_with = toUnicode(starts_with.lower())
            if starts_with in ascii_lowercase:
                filter_or.append(LibraryTitle.simple_title.startswith(starts_with))
            else:
                ignore = []
                for letter in ascii_lowercase:
                    ignore.append(LibraryTitle.simple_title.startswith(toUnicode(letter)))
                filter_or.append(not_(or_(*ignore)))

        if search:
            filter_or.append(LibraryTitle.simple_title.like('%%' + search + '%%'))

        if filter_or:
            q = q.filter(or_(*filter_or))

        q = q.order_by(asc(LibraryTitle.simple_title))

        if limit_offset:
            splt = limit_offset.split(',')
            limit = splt[0]
            offset = 0 if len(splt) is 1 else splt[1]
            q = q.limit(limit).offset(offset)

        results = q.all()

        movies = []
        for movie in results:
            temp = movie.to_dict(self.default_dict)
            movies.append(temp)

        return movies

    def availableChars(self, status = ['active']):

        chars = ''

        db = get_session()

        # Make a list from string
        if not isinstance(status, (list, tuple)):
            status = [status]

        q = db.query(Movie) \
            .join(Movie.library, Library.titles) \
            .options(joinedload_all('library.titles')) \
            .filter(LibraryTitle.default == True) \
            .filter(or_(*[Movie.status.has(identifier = s) for s in status]))

        results = q.all()

        for movie in results:
            char = movie.library.titles[0].simple_title[0]
            char = char if char in ascii_lowercase else '#'
            if char not in chars:
                chars += char

        return chars

    def listView(self):

        params = getParams()
        status = params.get('status', ['active'])
        limit_offset = params.get('limit_offset', None)
        starts_with = params.get('starts_with', None)
        search = params.get('search', None)

        movies = self.list(status = status, limit_offset = limit_offset, starts_with = starts_with, search = search)

        return jsonified({
            'success': True,
            'empty': len(movies) == 0,
            'movies': movies,
        })

    def charView(self):

        params = getParams()
        status = params.get('status', ['active'])
        chars = self.availableChars(status)

        return jsonified({
            'success': True,
            'empty': len(chars) == 0,
            'chars': chars,
        })

    def refresh(self):

        params = getParams()
        db = get_session()

        movie = db.query(Movie).filter_by(id = params.get('id')).first()

        # Get current selected title
        default_title = ''
        for title in movie.library.titles:
            if title.default: default_title = title.title

        if movie:
            #addEvent('library.update.after', )
            fireEventAsync('library.update', identifier = movie.library.identifier, default_title = default_title, force = True)
            fireEventAsync('searcher.single', movie.to_dict(self.default_dict))

        return jsonified({
            'success': True,
        })

    def search(self):

        params = getParams()
        cache_key = '%s/%s' % (__name__, urlencode(params))
        movies = Env.get('cache').get(cache_key)

        if not movies:
            movies = fireEvent('movie.search', q = params.get('q'), merge = True)
            Env.get('cache').set(cache_key, movies)

        return jsonified({
            'success': True,
            'empty': len(movies) == 0 if movies else 0,
            'movies': movies,
        })

    def add(self, params = {}, force_readd = True):

        library = fireEvent('library.add', single = True, attrs = params, update_after = False)

        # Status
        status_active = fireEvent('status.add', 'active', single = True)
        status_snatched = fireEvent('status.add', 'snatched', single = True)

        default_profile = fireEvent('profile.default', single = True)

        db = get_session()
        m = db.query(Movie).filter_by(library_id = library.get('id')).first()
        do_search = False
        if not m:
            m = Movie(
                library_id = library.get('id'),
                profile_id = params.get('profile_id', default_profile.get('id'))
            )
            db.add(m)
            fireEvent('library.update', params.get('identifier'), default_title = params.get('title', ''))
            do_search = True
        elif force_readd:
            # Clean snatched history
            for release in m.releases:
                if release.status_id == status_snatched.get('id'):
                    release.delete()

            m.profile_id = params.get('profile_id', default_profile.get('id'))
        else:
            log.debug('Movie already exists, not updating: %s' % params)

        if force_readd:
            m.status_id = status_active.get('id')

        db.commit()

        movie_dict = m.to_dict(self.default_dict)

        if force_readd or do_search:
            fireEventAsync('searcher.single', movie_dict)

        return movie_dict


    def addView(self):

        params = getParams()

        movie_dict = self.add(params)

        return jsonified({
            'success': True,
            'added': True,
            'movie': movie_dict,
        })

    def edit(self):

        params = getParams()
        db = get_session()

        ids = params.get('id').split(',')
        for movie_id in ids:

            m = db.query(Movie).filter_by(id = movie_id).first()
            m.profile_id = params.get('profile_id')

            # Default title
            if params.get('default_title'):
                for title in m.library.titles:
                    title.default = params.get('default_title').lower() == title.title.lower()

            db.commit()

            fireEvent('movie.restatus', m.id)

            movie_dict = m.to_dict(self.default_dict)
            fireEventAsync('searcher.single', movie_dict)

        return jsonified({
            'success': True,
        })

    def delete(self):

        params = getParams()
        db = get_session()

        status = fireEvent('status.add', 'deleted', single = True)

        ids = params.get('id').split(',')
        for movie_id in ids:
            movie = db.query(Movie).filter_by(id = movie_id).first()
            movie.status_id = status.get('id')
            db.commit()

        return jsonified({
            'success': True,
        })

    def restatus(self, movie_id):

        active_status = fireEvent('status.get', 'active', single = True)
        done_status = fireEvent('status.get', 'done', single = True)

        db = get_session()

        m = db.query(Movie).filter_by(id = movie_id).first()

        if not m.profile:
            return

        log.debug('Changing status for %s' % (m.library.titles[0].title))

        move_to_wanted = True

        for t in m.profile.types:
            for release in m.releases:
                if t.quality.identifier is release.quality.identifier and (release.status_id is done_status.get('id') and t.finish):
                    move_to_wanted = False

        m.status_id = active_status.get('id') if move_to_wanted else done_status.get('id')

        db.commit()
