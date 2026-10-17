export interface HistorySession {
  id: string;
  date: string;
  titleJapanese: string;
  topicName: string;
  length: 'Short' | 'Medium' | 'Long';
  speedCharsPerMinute: number;
  helpsPerHundred: number;
  scoreCorrect: number;
  scoreTotal: number;
}
