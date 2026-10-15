# JP Reading Practice

Ich möchte meine App Suite zum Japanischlernen um eine weitere App erweitern.
Der Fokus dieser App soll das Lesen-Üben sein.
Dabei soll aber auf den aktuellen Wissenstand aus anderen Apps, vor allem [Kanji Trainer](https://github.com/tkober/kanji-trainer) zurückgegriffen werden.
Übungstexte sollen LLM-basiert generiert und auf das aktuelle Niveau angepasst sein.


## Technical Requirements
- Die App soll auf [Sumi UI](https://github.com/tkober/sumi-ui) basieren und im look and feel den anderen entsprechen.
- Die App soll in die Schnellauswahl in der top navigation in den anderen apps auftauchen. 
Falls noch nicht vorhanden sollte hier vielleicht die Liste der Apps immer aus einem Endpoint von [Kanazawa Dashboard](https://github.com/tkober/kanazawa-dashboard) kommen, sodass neue Apps nicht immer in allen anderen gepflegt werden müssen.
- Analoge Einbindung von OpenAI Models wie in [JP Conversation Practice](https://github.com/tkober/jp-conversation-practice) (nur halt nicht whisper, sondern normal)
- Anbindung von [Kanji Trainer](https://github.com/tkober/kanji-trainer) via MCP


## Functional Requirements
- App auf Englisch, wie der Rest der App Suite.
- Einfache Generierung von Texten basierend auf dem aktuellen Lernfortschritt, aber nicht komplett darauf beschränkt.
- Es können also durchaus auch Kanji vorkommen die noch nicht gelernt wurden.
- Der Anteil sollte aber einstellbar und per default nicht übermäßig sein.
- Für bisher unbekannte Kanji/Lesungen soll furigana angezeigt werden.
- Das Niveau des Textes soll sich zum Einen aus den bisher bekannten Kanji und auch aus dem JLPT Level steuern lassen.
- Das heißt nicht, dass gar nichts drin vorkommen darf, was z.b. über JLPT N4 ist, aber es muss in einem gesunden, einstellbaren Verhältnis stehen.
- Vielleicht durch Multi-slider die Anteile der einzelnen Level einstellbar.
- In der Leseansicht soll Hilfsmittel geben, wie die Anzeige von Furigana, Übersetzungen einzelner Wörter oder Satzteile usw.
- Vielleicht auch eine Chatfunktion um hilfe vom LLM zu bekommen.
- Mit dem Start der Lektion, also nach dem Generieren soll getrackt werden wie lange man brauch zum Lesen, welche Hilfen man in Anspruch genommen hat und sow weiter.
- Dies soll dann getrackt werden um daraus aussagekräftige Statistiken für den Fortschritt und die Aktuellen Fähigkeiten ableiten zu können.
- Beispielswiese "Wörter pro Mminute", "Benötigte Hilfestellungen pro Wörter", "Leseniveau" usw.
- Bei der Textgenerierung soll es vorgefertigte Themen geben auf deren Grundlage Texte generiert werden wie zum Beispiel "Aktuelles Tagesgeschehen", "Geschichte", usw.
- Die Textlänge soll auch einstellbar sein. Am besten in der Anzahl an Wörtern und auf Grundlage der aktuellen Speed dann mit einer Anzeige wie lange die Übung vorraussichtlich dauern wird.
- Ebenfalls einstellbar soll der Stil-Mix sein. Also eher formal oder mehr alltagssprache usw.
- Die UI muss intuitiv und einfach sine. Durch clicken auf Wörter oder Sätze/Teilsätze möchte ich beispielsweise schon optionen angeboten bekommen wie "Übersetzen", "Erklären", "Grammatik Erklären"

## Offene Fragen
- Welche Statistiken machen Sinn
- Wie halten wir das Generieren simpel genug, dass man die App gerne nutzt, aber dass sich dennoch die Textauswahl steuern lässt.
- Sollen wir ein LLM auf Grundlage der vergangen Texte und des Niveaus vielleicht auch Vorschläge für die Beschaffenheit des nächsten Texts machen lassen, über einen Button "KI basiert"
- Wo liegt der MCP Server? [Kanji Trainer](https://github.com/tkober/kanji-trainer) oder hier in der App/in dem compose stack. Wenn er im [Kanji Trainer](https://github.com/tkober/kanji-trainer) stack liegt wäre es einfachher Änderungen an der Kanji App direkt im MCP Server zu spiegeln.


## Related Projects
- [Kanji Trainer](https://github.com/tkober/kanji-trainer)
- [JP Conjugation](https://github.com/tkober/jp-conjugation)
- [JP Conversation Practice](https://github.com/tkober/jp-conversation-practice)
- [Katakana Reading](https://github.com/tkober/katakana-reading)
- [Compose Stack Unraid](https://github.com/tkober/compose-stacks-unraid)
- [Sumi UI](https://github.com/tkober/sumi-ui)
- [Kanazawa Dashboard](https://github.com/tkober/kanazawa-dashboard)
