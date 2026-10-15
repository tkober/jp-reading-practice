import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideHttpClient, withFetch } from '@angular/common/http';
import {
  provideRouter,
  withComponentInputBinding,
  withInMemoryScrolling,
} from '@angular/router';
import { provideSumi } from 'sumi-ui/core';

import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ anchorScrolling: 'enabled', scrollPositionRestoration: 'enabled' }),
    ),
    provideHttpClient(withFetch()),
    // `accent`, `motif`, `pattern` and `companion` are all still placeholders
    // until the real design is picked in tkober/sumi-ui#25 -- `accent:
    // 'tokiwa'` is the preset sumi-ui added for this app (docs/concept.md's
    // tokiwa-iro green), the others are provisional choices.
    provideSumi({ accent: 'tokiwa', motif: 'moon', pattern: 'sayagata', companion: 'fukurou' }),
  ],
};
