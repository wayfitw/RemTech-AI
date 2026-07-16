# Корневые сертификаты «Russian Trusted CA» (Минцифры)

Нужны для TLS-проверки росгос-доменов (zakupki.gov.ru / ЕИС), чьи сертификаты
выпущены национальным УЦ Минцифры, отсутствующим в стандартном хранилище
(certifi/Mozilla). Подключаются в `services/websearch.py` ТОЛЬКО для *.gov.ru —
проверка сертификатов остаётся включённой (issue #35).

- `russian_trusted_root_ca.pem` — корневой (самоподписанный) «Russian Trusted Root CA».
- `russian_trusted_sub_ca_rsa2024.pem` — промежуточный RSA-2024, которым подписан
  сертификат zakupki.gov.ru (сервер его не отдаёт в handshake, поэтому храним рядом).

Источник: gu-st.ru / AIA-ссылка в сертификате ЕИС (nuc-cdp.digital.gov.ru).
При смене промежуточного УЦ (обычно раз в год) — обновить этот файл: взять URL из
`openssl x509 -in <leaf> -text | grep "CA Issuers"`.
