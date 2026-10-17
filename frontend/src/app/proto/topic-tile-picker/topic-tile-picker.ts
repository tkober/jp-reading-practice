// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// A grid of large topic tiles (glyph + name), including a dedicated
// "Surprise me" tile. Sumi UI has `sumi-card` for a generic flat container
// but nothing for a selectable picker grid, so this builds its own tiles
// styled only with `--sumi-*` tokens.
import { Component, input, output } from '@angular/core';

export interface TopicTileOption {
  id: string;
  glyph: string;
  name: string;
}

@Component({
  selector: 'proto-topic-tile-picker',
  templateUrl: './topic-tile-picker.html',
  styleUrl: './topic-tile-picker.scss',
  host: { class: 'proto-topic-tile-picker' },
})
export class TopicTilePicker {
  readonly topics = input.required<readonly TopicTileOption[]>();
  readonly selectedId = input<string | null>(null);
  /** Appended after `topics` as its own tile. */
  readonly surpriseId = input<string>('surprise');

  readonly select = output<string>();

  protected onSelect(id: string): void {
    this.select.emit(id);
  }
}
