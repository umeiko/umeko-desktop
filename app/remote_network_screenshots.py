"""Capture the live remote environment settings in the offscreen acceptance."""
from __future__ import annotations

import json
import math
from pathlib import Path


class NetworkSettingsShots:
    def __init__(self, acceptance, *, environment='dev-server', host_alias='dev-server', output=None):
        self.owner = acceptance
        self.backend = acceptance.backend
        self.window = acceptance.engine.rootObjects()[0]
        assert acceptance.app.platformName() == 'offscreen', 'Requires the existing offscreen app'
        assert environment and host_alias
        self.environment, self.host_alias = environment, host_alias
        self.session = self.backend._view.id
        self.output = Path(output or acceptance.directory / 'settings-screenshots')
        self.output.mkdir(parents=True, exist_ok=True)

    def find(self, name):
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == name:
                return item
            pending.extend(item.childItems())
        return None

    def row(self):
        return next((row for row in self.backend.remoteEnvironments
                     if row.get('name') == self.environment), {})

    def invariant(self):
        assert self.backend._view.id == self.session, 'Screenshot changed the established chat session'
        row = self.row()
        assert row.get('host') == self.host_alias, ('Wrong remote host/fixture alias', row)
        return row

    def open_settings(self):
        from PySide6.QtCore import QMetaObject
        assert self.backend.saveDesktopSettings('{"remoteWorkspaceEnabled":true}')
        self.window.setProperty('settingsTab', 3)
        self.window.setProperty('page', 'settings')
        self.owner.wait(lambda: self.find('umekoDesktopSettings') is not None, 15, 'desktop settings object')
        if not self.find('umekoDesktopSettings').isVisible():
            button = self.find('openUmekoDesktopSettingsButton')
            assert button is not None and button.isVisible() and button.isEnabled()
            assert QMetaObject.invokeMethod(button, 'clicked'), 'Cannot open desktop settings'
        self.owner.wait(lambda: self.find('remoteNetworkSharingToggle') is not None
                        and self.find('remoteNetworkSharingToggle').isVisible(), 15, 'network sharing toggle')

    def card(self):
        item = self.find('remoteNetworkSharingToggle')
        while item is not None:
            # SectionCard.qml derives from the real QtQuick.Controls Frame.
            if item.inherits('QQuickFrame') or item.metaObject().className().startswith('SectionCard_'):
                return item
            item = item.parentItem()
        raise AssertionError('Network sharing SectionCard ancestor is missing')

    def place_card(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtTest import QTest
        card = self.card()
        # Offscreen surface only: fit the entire actual card, preserving its
        # normal QML layout. No OS window, focus, mouse, or keyboard API is used.
        self.window.resize(max(self.window.width(), 1280),
                           max(self.window.height(), math.ceil(card.height() + 350)))
        QTest.qWait(100)
        scroll = self.find('settingsScroll')
        assert scroll is not None
        flick = scroll.property('contentItem')
        top = card.mapToItem(flick, QPointF(0, 0)).y() + float(flick.property('contentY'))
        maximum = max(0., float(flick.property('contentHeight')) - flick.height())
        flick.setProperty('contentY', max(0., min(maximum, top - 12)))
        QTest.qWait(100)
        return card, flick

    def capture(self, stage, *, enabled, language):
        from PySide6.QtCore import QPointF, QRect, QRectF
        from PySide6.QtTest import QTest
        assert stage in ('on', 'off') and type(enabled) is bool and language in ('zh', 'en')
        row = self.invariant()
        assert bool(self.backend.remoteNetworkEnabled) is enabled, 'Capture must follow the real switch action'
        assert row.get('state') == 'connected', ('Capture requires established remote connection', row)
        expected_network = 'local' if enabled else 'remote'
        assert row.get('networkStatus', {}).get('network') == expected_network, row
        # This is the product's actual localization API. It restarts the Pi
        # process for UI language; it does not create a new chat session.
        self.backend.setLanguage(language)
        self.owner.wait(lambda: self.backend.language == language and not self.backend.busy,
                        30, 'localized existing session')
        self.invariant()
        self.open_settings()
        toggle = self.find('remoteNetworkSharingToggle')
        self.owner.wait(lambda: bool(toggle.property('checked')) is enabled, 15, 'rendered switch state')
        status_name = 'remoteEnvironmentNetwork_' + self.environment
        label = self.find(status_name)
        assert label is not None and label.isVisible(), ('Missing live environment network label', status_name)
        expected = {
            ('zh', True): '服务器正在使用本机网络',
            ('zh', False): '本机网络共享已关闭',
            ('en', True): "The server is using this computer's network",
            ('en', False): 'Network sharing is off',
        }[(language, enabled)]
        self.owner.wait(lambda: label.property('text') == expected, 15, 'localized network status')
        card, flick = self.place_card()
        QTest.qWait(80)
        # Capture exactly the current Qt-rendered frame. The only image operation
        # is a crop to the network SectionCard, with no repaint or annotation.
        image = self.window.grabWindow()
        assert not image.isNull(), 'Qt returned an empty frame'
        scene = QRectF(card.mapToScene(QPointF(0, 0)), card.size())
        viewport = QRectF(flick.mapToScene(QPointF(0, 0)), flick.size())
        assert viewport.adjusted(-1, -1, 1, 1).contains(scene), ('Card is clipped', scene, viewport)
        sx, sy = image.width() / self.window.width(), image.height() / self.window.height()
        crop = QRect(math.floor(scene.left() * sx), math.floor(scene.top() * sy),
                     math.ceil(scene.width() * sx), math.ceil(scene.height() * sy))
        assert image.rect().contains(crop), ('Card exceeds captured frame', crop, image.rect())
        path = self.output / f'remote-network-{stage}-{language}.png'
        assert image.copy(crop).save(str(path)), ('Cannot save Qt frame crop', path)
        evidence = {'path': str(path), 'stage': stage, 'language': language,
                    'enabled': enabled, 'session': self.session,
                    'environment': self.environment, 'hostAlias': self.host_alias,
                    'network': expected_network, 'label': label.property('text'),
                    'toggleChecked': bool(toggle.property('checked')),
                    'renderSource': 'QQuickWindow.grabWindow, actual SectionCard crop',
                    'pixels': [crop.width(), crop.height()]}
        self.owner.note('network-settings-screenshot', **evidence)
        path.with_suffix('.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        return evidence

    def pair(self, stage, *, enabled):
        previous_page = self.window.property('page')
        previous_language = self.backend.language
        try:
            return [self.capture(stage, enabled=enabled, language=language) for language in ('zh', 'en')]
        finally:
            self.backend.setLanguage(previous_language)
            self.window.setProperty('page', previous_page)
            self.invariant()
