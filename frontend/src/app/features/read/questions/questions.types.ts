import type { SumiChoiceOption } from 'sumi-ui/practice';

export interface ComprehensionQuestion {
  id: string;
  textEnglish: string;
  options: readonly SumiChoiceOption[];
  correctOptionId: string;
}
