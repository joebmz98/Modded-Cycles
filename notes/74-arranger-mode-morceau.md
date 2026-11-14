# 74 — Arranger : Program Change, chaînes de patterns et un mode morceau

Rédigé le 14/11/2026 pour le fork Arranger de Joe (`joebmz98/Modded-Cycles`) : un mode morceau piloté par
l'application web Cycles Arranger (`arranger/`, protocole SysEx dans `arranger/SONG-PROTOCOL.md`). Question : où
l'OS change-t-il de pattern, et sur quoi un mode morceau peut-il s'accrocher ? Adresses : VA de l'OS 1.13.

## Réponse courte

- Un Program Change reçu aboutit à **`0x40055cd6(paires, n)`**, qui charge une **chaîne de patterns** : jusqu'à 64
  paires `{pattern*, kit*}` en `0x40a7863c`. L'OS sait déjà enchaîner des patterns ; un PC charge simplement une
  chaîne d'un seul pattern. `[FAIT]`
- L'interruption du séquenceur **arme** l'entrée suivante sur le **dernier pas** du pattern en cours, puis
  **bascule** au retour au début : l'index de la chaîne avance et **revient à 0** après la dernière entrée.
  `[FAIT en émulation]` pour l'avance et le bouclage (`tools/emu/test_chain.py`, 6 contrôles).
- Un mode morceau v1 n'a donc **pas besoin de crochet dans l'interruption** : un moteur dans la tâche d'interface
  écrit l'entrée suivante par `0x40055cd6`, exactement comme un Program Change, à tout moment avant le dernier pas.
  `[HYP]` tant que ce n'est pas essayé sur la machine.
- Au passage, pour le mode « live » de l'application : un PC reçu *pendant* le dernier pas arrive en même temps que
  l'armement. D'où le « quelques ms avant » d'Elektron, et le PC envoyé 4 pas en avance par défaut par l'application.
  `[FAIT]` pour l'endroit de l'armement.

## 1. Du MIDI IN à la tâche d'interface

| Adresse | Rôle |
|---|---|
| `0x4007f6a8` | Découpe des octets en messages : temps réel (`F8..FF`) seuls, SysEx jusqu'à `F7`, messages de canal selon leur longueur (table `0x40112874`). Chaque message va dans la file du port `[port × 52 + 0x40f1bf48]`, signalée par `[… + 0x4c]` `[FAIT]` |
| `0x4007f658(port, file, sem)` | Relie un port à une file ; `0x40080674` relie les ports 0, 1, 2 à `0x40fc00a8`, `0x40fc0088`, `0x40fc0068`, un seul sémaphore `0x40fc0060` `[FAIT]` |
| `0x40080674` | Tâche MIDI : attend `0x40fc0060`, vide les trois files, filtre (`0x40044e32`), envoie les messages de canal par **`0x401129f4[statut >> 4]`**, le canal comparé au canal AUTO `0x40a70100` `[FAIT]` |
| `0x401129f4` | Table des gestionnaires : `8` note off `0x400816fa`, `9` note on `0x40081a42`, `B` CC `0x40080ac4`, **`C` PC `0x40080c3e`**, les autres ne font rien `[FAIT]` |
| `0x40080c3e` | Gestionnaire du PC. Sort tout de suite si PCH IN est éteint (`0x40a70154`). Canal : `0x40a7013c` (canal PCH IN), négatif = AUTO, alors comparé à `0x40a70100`. Construit un message d'interface de 32 o : type **12**, sous-type **5**, canal, drapeau de port, programme ; le poste par `0x40080bf6` dans la file de l'interface `*0x40149250` `[FAIT]` |
| `0x40012cf4(obj)` | Lecture de PCH IN pour le menu (`obj` = `0x4000eb90(0x400cf866())`, champ `+0x94` de `vtable[10]`) ; PCH OUT en `+0x98` `[FAIT]` |

## 2. La tâche d'interface fait du PC une chaîne d'un pattern

Dans l'aiguillage des messages de la tâche d'interface, `0x40008392` lit le sous-type (`0x40073990`, champ `+16`)
et, pour **5** :

```
programme = msg.charge[16]                     ; 0..95, au-delà ignoré
si (*0x40fe4228 == 0) rien                      ; [HYP] projet chargé / prêt
pattern = 0x406fa040 + programme × 30710        ; banque de patterns du séquenceur (notes/32)
kit     = 0x409c9c80 + programme × 7094
paire   = alloc(8) ; memmove(paire, {pattern, kit}, 8)
0x40055cd6(paire, 1)                            ; chaîne d'un pattern
libère(paire)
```
`[FAIT]` (`0x400083a0..0x40008418`)

## 3. La chaîne

| Adresse | Rôle |
|---|---|
| `0x40a7863c` | Chaîne : 64 × `{pattern*, kit*}` `[FAIT]` |
| `0x40a78634` | Index de l'entrée jouée, `-1` avant la première `[FAIT]` |
| `0x40a78638` | Longueur de la chaîne `[FAIT]` |
| `0x40055cd6(paires, n)` | **Pose la chaîne** : copie jusqu'à 64 paires, index = -1, longueur = n. À l'arrêt (`0x40a7883c == 0`) : charge l'entrée 0 tout de suite (`0x40055c38`). En lecture avec un changement déjà armé (`0x40a78920`) : réarme sur la nouvelle entrée 0 (`0x4005419e`). Sinon attend l'armement `[FAIT]` |
| `0x4005428a()` | Longueur de la chaîne `[FAIT en émulation]` |
| `0x40054292(tampon, max)` | Recopie la chaîne `[FAIT]` |
| `0x4005416a()` | Entrée courante (d0 = pattern, d1 = kit) `[FAIT]` |
| `0x40055c38(pattern, kit)` | Charge un pattern et un kit comme courants : `0x40a7887c` = pattern, `0x40a78888` = kit `[FAIT]` |
| `0x40a7883c` | Séquenceur en lecture `[FAIT]` |
| `0x40a7887c` / `0x40a78888` | Pointeurs du pattern / kit courants `[FAIT]` |
| `0x40a78880` / `0x40a7888c` | Pointeurs du pattern / kit suivants, posés à l'armement `[FAIT]` |
| `0x40a78920` | Changement armé `[FAIT]` |
| `0x40a78840` | Compteur de pas du pattern joué `[FAIT]` |
| `0x40a7889c` | `-1`, ou un nombre de pas qui remplace la longueur du pattern pour l'armement `[HYP]` longueur de changement |

## 4. Armement et bascule, dans l'interruption du séquenceur

La routine qui se termine par `rte` en `0x40055a7a` tourne une fois par pas.

- **Armement** (`0x4005559a..0x40055ad8`) : index suivant = `index < 0 ? 0 : index + 1`, ramené dans la longueur ;
  lit cette entrée. Si la chaîne n'a qu'une entrée égale au pattern joué, rien ne change. Sinon, quand le compteur
  de pas atteint le dernier pas (longueur − 1, ou `0x40a7889c` − 1), range le pattern et le kit suivants
  (`0x40a78880`, `0x40a7888c`), appelle `0x4005419e` (préparation du pattern suivant) et pose `0x40a78920 = 1`. `[FAIT]`
- **Bascule** (`0x4005563e..0x40055698`) : au retour au début, si un changement est armé, efface le drapeau, avance
  l'index (`-1 → 0`, sinon `+1`, retour à 0 à la longueur) et charge les pointeurs de l'entrée. `[FAIT en émulation]`

Conséquence : ce qui est écrit dans la chaîne avant le dernier pas du pattern joué est ce qui sera joué ensuite.
Une écriture pendant le dernier pas arrive trop tard pour ce retour au début.

## 5. Conception du mode morceau v1

- **SysEx entrant** : un gestionnaire sur une commande libre du routeur SysEx (`0x40081348`, table `0x40148d08`,
  notes/15) range la table du morceau (lignes : pattern, répétitions, masque de mutes, tempo ;
  `arranger/SONG-PROTOCOL.md`) dans de la SDRAM libre.
- **Moteur** dans le tick à 30 Hz de la tâche d'interface (`0x400081e4`, comme le step record, notes/73) :
  - un début de pattern se voit à `0x40a78840` qui redescend (retour au début), ou à `0x40a7887c` qui change ;
  - à chaque début : décompte des répétitions de la ligne ; à la dernière, écrit le pattern de la ligne suivante par
    `0x40055cd6(&paire, 1)` ; au début d'une ligne, applique ses mutes et son tempo (`0x40058bb4`, notes/38) ;
  - à la fin du morceau : chaîne d'un pattern égal au dernier, puis arrêt à son retour au début.
- **Limite** : à 30 Hz, le tick ne voit chaque retour au début que si un pattern dure plus de 33 ms (un pas à
  546 BPM dure 27 ms). Un pattern d'un pas à tempo extrême demandera un crochet sur la bascule (`0x4005563e`) : v2.
- **Variante** : un morceau de 64 passages de pattern au plus tiendrait dans une seule chaîne, répétitions
  dépliées. La chaîne boucle d'elle-même : il faudrait quand même le moteur pour s'arrêter à la fin et poser les mutes.

## 6. Preuve

`tools/emu/test_chain.py --cycles firmware/model-cycles_OS1.13.syx` projette le MAIN OS d'origine dans Unicorn
(ColdFire V4e), appelle `0x40055cd6` avec une chaîne de quatre (A01, A01, A02, A04) en lecture, puis exécute six
fois la bascule `0x4005563e..0x400556a0` avec un changement armé :

```
PASS chain set while playing: length 4, index -1
PASS chain holds the four pattern pointers
PASS 0x4005428a returns the chain length
swaps (index, next program, armed): [(0, 0, 0), (1, 0, 0), (2, 1, 0), (3, 3, 0), (0, 0, 0), (1, 0, 0)]
PASS index steps 0, 1, 2, 3, then loops to 0
PASS next pattern follows the chain entries
PASS the armed flag is consumed by each swap
```

`[À FAIRE]` L'armement dans une vraie séquence (étendre `seqrig.py` à l'interruption des pas), et tout sur la machine.

## 7. Suite

1. `[À FAIRE]` Choisir les numéros de commande SysEx : relever les entrées prises de la table du routeur pour le produit `0x11`.
2. `[À FAIRE]` Place libre pour le moteur et la table du morceau : `REGISTRY.md`.
3. `[À FAIRE]` Écrire le moteur en C (`tools/machines/song/`), le générateur `gen_song.py`, le tweak `song-mode`.
4. `[À FAIRE]` Le prouver en émulation : écriture SysEx → table ; tick → appels de `0x40055cd6` aux bons pas.
5. `[À FAIRE]` Essai sur la machine, avec une interface USB-MIDI sous la main pour la récupération (RECOVERY.md).
