import type { McOption } from '../../../proto/mc-question/mc-question';

export interface ComprehensionQuestion {
  id: string;
  textEnglish: string;
  options: readonly McOption[];
  correctOptionId: string;
}
