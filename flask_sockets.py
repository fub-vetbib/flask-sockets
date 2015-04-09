# -*- coding: utf-8 -*-

# Copyright (C) 2013-2014 Kenneth Reitz
# Copyright (C) 2014      David K. Hess
# Copyright (C) 2014      Jules Olleon
# Copyright (C) 2015      René Kijewski / Freie Universität Berlin
# License: MIT  http://opensource.org/licenses/MIT

from flask.helpers import _endpoint_from_view_func
from werkzeug.routing import Map, Rule, BuildError
from werkzeug.exceptions import NotFound


__all__ = ('Sockets',)


class WsUrlAdapterWrapper(object):
    def __init__(self, app_adapter, sockets_adapter):
        self.__app_adapter = app_adapter
        self.__sockets_adapter = sockets_adapter

    def build(self, endpoint, values=None, method=None, force_external=False, append_unknown=True):
        try:
            return 'ws' + self.__sockets_adapter.build(
                endpoint=endpoint,
                values=values,
                method=None,
                force_external=True,
                append_unknown=append_unknown,
            )[4:]
        except BuildError:
            return self.__app_adapter.build(
                endpoint=endpoint,
                values=values,
                method=method,
                force_external=force_external,
                append_unknown=append_unknown,
            )

    def __getattr__(self, attr):
        fun = getattr(self.__app_adapter, attr)
        setattr(self, attr, fun)
        return fun


class Sockets(object):
    def __init__(self, app=None):
        self.url_map = Map()
        self.view_functions = {}
        if app:
            self.init_app(app)

    def __create_url_adapter(self, url_map, request):
        if request is not None:
            return url_map.bind_to_environ(
                request.environ,
                server_name=self.app.config['SERVER_NAME']
            )
        elif self.app.config['SERVER_NAME'] is not None:
            return url_map.bind(
                self.app.config['SERVER_NAME'],
                script_name=self.app.config['APPLICATION_ROOT'] or '/',
                url_scheme=self.app.config['PREFERRED_URL_SCHEME']
            )

    def create_url_adapter(self, request):
        adapter_for_app = self.__create_url_adapter(self.app.url_map, request)
        adapter_for_sockets = self.__create_url_adapter(self.url_map, request)
        return WsUrlAdapterWrapper(adapter_for_app, adapter_for_sockets)

    def init_app(self, app):
        self.app = app
        self.app_wsgi_app = app.wsgi_app

        app.wsgi_app = self.wsgi_app
        app.create_url_adapter = self.create_url_adapter

    def route(self, rule, **options):
        def decorator(f):
            endpoint = options.pop('endpoint', None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f
        return decorator

    def add_url_rule(self, rule, endpoint, f, **options):
        if endpoint is None:
            endpoint = _endpoint_from_view_func(f)

        methods = options.pop('methods', None)
        options.setdefault('defaults', {}).setdefault('ws', None)

        self.url_map.add(Rule(rule, endpoint=endpoint, **options))
        self.view_functions[endpoint] = f

        if methods is None:
            methods = []
        self.app.add_url_rule(rule, endpoint, f, methods=methods, **options)

    def wsgi_app(self, environ, start_response):
        if environ.get('HTTP_UPGRADE', '').lower() != 'websocket':
            return self.app_wsgi_app(environ, start_response)

        endpoint, values = self.url_map.bind_to_environ(environ).match()
        view_function = self.view_functions[endpoint]
        values['ws'] = environ['wsgi.websocket']

        with self.app.app_context():
            with self.app.request_context(environ):
                view_function(**values)
                return []
