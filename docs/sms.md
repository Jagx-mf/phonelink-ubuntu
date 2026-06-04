# Panneau SMS

Maquette d'interface pour **lire et écrire des SMS** depuis Ubuntu.

## État actuel : UI seule, données fictives

Le panneau (`app/ui/sms_window.py`) est entièrement fonctionnel côté interface :

- liste des conversations à gauche ;
- fil de la conversation sélectionnée à droite (bulles entrant/sortant) ;
- champ de saisie + bouton **Envoyer** en bas.

Le bouton Envoyer est **simulé** : le message s'ajoute localement au fil pour
démontrer l'interaction, mais **rien n'est réellement transmis**. Un bandeau le
rappelle en haut de la fenêtre.

Les données proviennent de `MockSmsBackend` (`app/core/sms.py`) — des
conversations fictives, aucune connexion à un téléphone.

## Pourquoi il faut une app compagnon Android

Android **n'expose pas** sa base SMS à une application de bureau tierce :

- le **Bluetooth** ici ne sert qu'à l'audio (A2DP / HSP-HFP), pas aux SMS ;
  le profil MAP (Message Access) n'est pas implémenté et reste partiel/instable
  côté Android ;
- **ADB** ne donne pas accès à la base SMS sans root ni autorisation spéciale ;
- la contrainte projet exclut explicitement **scrcpy**, **KDE Connect** et
  **GSConnect**.

Le SMS réel nécessitera donc une **application compagnon Android** (à développer)
qui, avec les permissions SMS de l'utilisateur, lit/envoie les messages et
expose une petite API locale (par ex. sur Wi-Fi / ADB) que PhoneLink Ubuntu
interrogera.

## Architecture : prêt à brancher un vrai backend

Le couplage UI ↔ données passe par une seule interface :

```
app/core/sms.py
  ├─ Message, Conversation        → modèle de données
  ├─ SmsBackend (ABC)             → contrat : list_conversations / get_conversation
  │                                          / send_message / is_ready
  ├─ MockSmsBackend               → données fictives (aujourd'hui)
  └─ get_backend()                → point d'injection unique (singleton)
```

`sms_window.py` ne dépend **que** de `SmsBackend`. L'étape vers le réel est
**amorcée** : `AndroidCompanionBackend(SmsBackend)` existe désormais.

### Sélection du backend

`get_backend()` choisit, dans cet ordre :

1. un backend forcé via `set_backend(...)` (tests, futur sélecteur dans l'UI) ;
2. sinon la variable d'environnement `PHONELINK_SMS_BACKEND` :
   - `mock` (défaut) → `MockSmsBackend`, données fictives ;
   - `android` → `AndroidCompanionBackend`, via `app/core/android_bridge.py` ;
3. sinon le mock.

```
PHONELINK_SMS_BACKEND=android python3 main.py
```

`AndroidCompanionBackend` s'appuie sur `android_bridge` qui reste lui-même en
mode **mock** en V0.4 (aucun réseau réel). Il est donc sélectionnable sans
téléphone : `is_ready` renvoie simplement `False` tant qu'aucune app compagnon
réelle ne répond à `/health` avec la permission SMS — le bandeau « simulé »
reste alors affiché et l'envoi reste simulé.

Pour activer le **vrai** envoi : implémenter le transport HTTP dans
`android_bridge._request()` puis passer le pont en mode `HTTP`. Voir
[`docs/android-backend-v0.4.md`](android-backend-v0.4.md).

**Aucune modification de l'UI n'est nécessaire à aucune de ces étapes.**
