#!/usr/bin/env python

import argparse
import inspect
import pathlib
import random
import re
from os import path, system
from urllib.parse import urlparse

import dbus
import requests
from bs4 import BeautifulSoup
from xdg import BaseDirectory


class DeepinDailyWallpaper:

    def __init__(self, source, change, clean, storage_path, bus):
        self._source = source
        self._change = change
        self._clean = clean
        self._storage_path = storage_path
        self._bus = bus

        # Make sure storage path exists
        pathlib.Path(self._storage_path).mkdir(parents=True, exist_ok=True)

    def run(self):
        self._set_wallpaper(self._fetch_wallpaper())

    def clean_up(self):
        if self._clean <= 0:
            return

        system('find {} -mtime +{} -delete'.format(self._storage_path, self._clean))

    @staticmethod
    def get_sources():
        pattern = re.compile(r'^_fetch_(\w+)_wallpaper$')
        methods = inspect.getmembers(DeepinDailyWallpaper, predicate=inspect.isroutine)

        return [pattern.sub(r'\1', v[0]) for v in methods if pattern.match(v[0])]

    def _fetch_wallpaper(self):
        # If self.source is any, randomly choose one
        source = self._source
        if self._source == 'any':
            source = random.choice(DeepinDailyWallpaper.get_sources())
        method = '_fetch_%s_wallpaper' % source

        return getattr(self, method)()

    def _fetch_bing_wallpaper(self):
        soup = self._soupify('https://www.bing.com/HPImageArchive.aspx?format=xml&idx=0&n=1&mkt=en-US')

        image = soup.select_one('urlBase')
        if image is None:
            raise RuntimeError('Image not found')

        uri = 'https://www.bing.com/{}_1920x1080.jpg'.format(image.text)
        file_name = 'https://www.bing.com/{}.jpg'.format(image.text)

        return self._download_image(uri, self._create_filename(file_name))

    def _fetch_natgeo_wallpaper(self):
        soup = self._soupify('http://www.nationalgeographic.com/photography/photo-of-the-day/')

        image = soup.find("meta", {"property": "og:image"})
        if image is None:
            raise RuntimeError('Image not found')

        uri = image['content']

        # The canonical link doesn't end in .jpg, so we add it for the sake of a decent file name
        file_name = soup.find("link", {"rel": "canonical"})
        file_name = '{}.jpg'.format(urlparse(file_name['href']).path.rstrip('/'))

        return self._download_image(uri, self._create_filename(file_name))

    def _fetch_wiki_wallpaper(self):
        soup = self._soupify('https://commons.wikimedia.org/wiki/Main_Page')

        image = soup.select_one('#mainpage-potd div a img')
        if image is None:
            raise RuntimeError('Image not found')

        # Strip off the thumb/ portion, and everything after the last / so we get the full rez image
        uri = image['src'].replace("thumb/", "")
        uri = uri[0:uri.rfind('/')]

        return self._download_image(uri, self._create_filename(uri))

    def _fetch_nasa_wallpaper(self):
        soup = self._soupify('https://apod.nasa.gov/apod/')

        image = soup.select_one('a[href^="image/"]')
        if image is None:
            raise RuntimeError('Image not found')

        uri = 'https://apod.nasa.gov/apod/{}'.format(image['href'])

        return self._download_image(uri, self._create_filename(uri))

    def _fetch_epod_wallpaper(self):
        soup = self._soupify('https://epod.usra.edu/blog/')

        image = soup.select_one('a.asset-img-link')
        if image is None:
            raise RuntimeError('Image not found')

        uri = image['href']
        file_name = self._create_filename('{}.jpg'.format(uri))

        return self._download_image(uri, file_name)

    def _download_image(self, uri, name):
        output_file = path.join(self._storage_path, name)

        if pathlib.Path(output_file).exists():
            return output_file

        r = requests.get(uri)
        if r.status_code != 200:
            raise RuntimeError('{} error downloading image'.format(r.status_code))

        with open(output_file, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)

        return output_file

    def _set_wallpaper(self, path):
        if self._change == 'wallpaper' or self._change == 'all':
            self._dbus_set('background', path)

        if self._change == 'greeter' or self._change == 'all':
            self._dbus_set('greeterbackground', path)

    def _dbus_set(self, which, path):
        self._bus.Set(which, path, dbus_interface='com.deepin.daemon.Appearance')
        pass

    @staticmethod
    def _create_filename(uri):
        return path.basename(urlparse(uri).path)

    @staticmethod
    def _soupify(uri):
        r = requests.get(uri)
        if r.status_code != 200:
            raise RuntimeError('{} error fetching IoD'.format(r.status_code))

        # Get some pretty xml
        return BeautifulSoup(r.content, 'lxml')


if __name__ == '__main__':
    default_storage_dir = path.join(BaseDirectory.save_data_path('ddw'), 'wallpapers')
    parser = argparse.ArgumentParser(description='Set a new wallpaper every day in Deepin DE!')
    parser.add_argument('--source', '-s', type=str, default='any', help="sets the source to use [all]",
                        choices=DeepinDailyWallpaper.get_sources() + ['any'])
    parser.add_argument('--change', '-c', type=str, default='all',
                        help="sets the wallpaper to change [all]",
                        choices=['wallpaper', 'greeter', 'all'])
    parser.add_argument('--clean', metavar='DAYS', type=int, default=7, help='clean up wallpapers older than X days')
    parser.add_argument('--storage-path', metavar='DIR', type=str, default=default_storage_dir,
                        help='set the storage directory for downloaded images [%s]' % default_storage_dir)

    args = vars(parser.parse_args())

    ddw = DeepinDailyWallpaper(**args,
                               bus=dbus
                               .SessionBus()
                               .get_object('com.deepin.daemon.Appearance', '/com/deepin/daemon/Appearance'))

    ddw.run()
    ddw.clean_up()
