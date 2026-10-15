import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SUMI_LAYOUT, type SumiAppShellBrand, type SumiNavItem } from 'sumi-ui/layout';

@Component({
  imports: [...SUMI_LAYOUT, RouterOutlet],
  selector: 'app-root',
  templateUrl: './app.html',
})
export class App {
  protected readonly brand: SumiAppShellBrand = { glyph: '読', name: 'JP Reading Practice' };

  // Fixed, unlike kanji-trainer's `computed()` nav -- there is no per-item
  // badge count yet (due reviews, lesson counts); this is a plain array
  // until a later issue gives one of these entries something to report.
  protected readonly nav: SumiNavItem[] = [
    { label: 'Read', link: 'read', icon: 'practice', exact: true },
    { label: 'History', link: 'history', icon: 'history' },
    { label: 'Stats', link: 'stats', icon: 'stats' },
    { label: 'Topics', link: 'topics', icon: 'scenarios' },
    { label: 'Settings', link: 'settings', icon: 'settings' },
  ];
}
