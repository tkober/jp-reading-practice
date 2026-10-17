// Prototype for a sumi-ui component — move to the library once the design is
// approved (#6).
//
// A segmented bar with five shares (N5...N1) and draggable boundaries
// between them. Sumi UI has `sumi-segmented-bar` (read-only, see its own
// doc comment) and a bare `sumiSlider` directive for a *single*-thumb native
// range input, but nothing that edits several proportional shares at once.
//
// Built from four overlaid native `<input type="range">` elements, one per
// boundary between two adjacent segments (there is no fifth boundary --
// N1's share is always "whatever is left"). Each range's own value is the
// *cumulative* percentage up to that boundary, which keeps the browser's
// own keyboard handling (arrow keys, Home/End, screen reader "slider" role)
// for free -- the classic way to build a multi-thumb slider without
// reaching for a library. Dragging a thumb past a neighbour is prevented by
// clamping each range's `min`/`max` to its neighbours' current values.
import { Component, computed, input, output } from '@angular/core';

export interface JlptShares {
  n5: number;
  n4: number;
  n3: number;
  n2: number;
  n1: number;
}

const LEVELS = ['n5', 'n4', 'n3', 'n2', 'n1'] as const satisfies readonly (keyof JlptShares)[];
const LABELS: Record<keyof JlptShares, string> = {
  n5: 'N5',
  n4: 'N4',
  n3: 'N3',
  n2: 'N2',
  n1: 'N1',
};
/** `--sumi-seq-1` is the lightest step; N5 (easiest) gets it, N1 the darkest. */
const COLORS: Record<keyof JlptShares, string> = {
  n5: 'var(--sumi-seq-1)',
  n4: 'var(--sumi-seq-2)',
  n3: 'var(--sumi-seq-3)',
  n2: 'var(--sumi-seq-4)',
  n1: 'var(--sumi-seq-5)',
};

interface Segment {
  level: keyof JlptShares;
  label: string;
  color: string;
  percent: number;
}

interface Boundary {
  /** Index into `LEVELS`: the boundary after this level. */
  afterIndex: number;
  value: number;
  min: number;
  max: number;
  ariaLabel: string;
}

@Component({
  selector: 'proto-jlpt-multi-slider',
  templateUrl: './jlpt-multi-slider.html',
  styleUrl: './jlpt-multi-slider.scss',
  host: { class: 'proto-jlpt-multi-slider' },
})
export class JlptMultiSlider {
  readonly shares = input.required<JlptShares>();
  readonly disabled = input(false);
  readonly ariaLabel = input('JLPT mix');

  readonly sharesChange = output<JlptShares>();

  /** Cumulative boundary after each of the first four levels (0-100). */
  private readonly cumulative = computed(() => {
    const shares = this.shares();
    const values: number[] = [];
    let sum = 0;
    for (const level of LEVELS) {
      sum += shares[level];
      values.push(sum);
    }
    return values; // 5 entries; the last is always 100 (not a boundary/thumb)
  });

  protected readonly segments = computed<Segment[]>(() => {
    const shares = this.shares();
    return LEVELS.map((level) => ({
      level,
      label: LABELS[level],
      color: COLORS[level],
      percent: shares[level],
    }));
  });

  protected readonly boundaries = computed<Boundary[]>(() => {
    const cumulative = this.cumulative();
    return [0, 1, 2, 3].map((i) => ({
      afterIndex: i,
      value: cumulative[i],
      min: i === 0 ? 0 : cumulative[i - 1],
      max: cumulative[i + 1],
      ariaLabel: `Boundary between ${LABELS[LEVELS[i]]} and ${LABELS[LEVELS[i + 1]]}`,
    }));
  });

  protected onBoundaryInput(afterIndex: number, rawValue: string): void {
    const cumulative = [...this.cumulative()];
    const min = afterIndex === 0 ? 0 : cumulative[afterIndex - 1];
    const max = cumulative[afterIndex + 1];
    const value = Math.min(max, Math.max(min, Number(rawValue)));
    cumulative[afterIndex] = value;

    const next: JlptShares = { n5: 0, n4: 0, n3: 0, n2: 0, n1: 0 };
    let previous = 0;
    LEVELS.forEach((level, i) => {
      const boundary = i < 4 ? cumulative[i] : 100;
      next[level] = Math.max(0, boundary - previous);
      previous = boundary;
    });
    this.sharesChange.emit(next);
  }
}
