---
name: einvoicing
description: Guides building and reviewing Colombian electronic invoicing (DIAN) - factura electrónica de venta, notas crédito y débito, documento equivalente POS, documento soporte, nómina electrónica, RADIAN, numbering, CUFE, signing, validación previa and contingency. Use when a task designs, implements, debugs or reviews electronic invoicing or any DIAN electronic document. Triggers on "factura electrónica", "CUFE", "nota crédito".
argument-hint: "[document type or question]"
---

# dynamia-colombia:einvoicing

Facts below were read from the DIAN normograma on 2026-10-23. **Before relying on a version, date or field, confirm it** with `dynamia-colombia:normativa` (the annex version and the compiled rule can change).

## Where the rules are
- Resolución 000165 de 2023 adopted the **Anexo Técnico de Factura Electrónica de Venta v1.9** and the **Anexo Técnico del Documento Equivalente Electrónico v1.0**; Resolución 000008 de 2024 fixed 1 May 2024 as the date to move from v1.8 to v1.9. Its articles are now compiled in **Resolución 000227 de 2025, Parte 1, Título 5** (sistema de facturación, documento soporte, nómina electrónica, RADIAN). Later resolutions (for example 000119 and 000189 de 2024, 000202 de 2025) modify articles: always read the compiled text.
- The annex (a large PDF, XML field tables and code lists) is the contract for your software; see `references/sources.md` of `normativa` for the links. If the PDF cannot be read in one request, work from the section the user points to.

## Read `references/` as needed
| Need | File |
|---|---|
| Which documents exist, who must issue, what makes an invoice valid | `references/documents.md` |
| Designing or debugging the issuing flow (numbering, XML, signature, validation, delivery, events) | `references/flow.md` |
| Reviewing an invoicing implementation | `references/review-checklist.md` |

## Ground rules
1. **An electronic invoice exists only when the DIAN validates it and it is delivered to the buyer.** Generating a signed XML is not issuing it.
2. Never reuse or skip a consecutive number; a rejected document keeps its problem, you fix the data and send a new valid document under the rules of the annex, you do not silently renumber.
3. Dates and times are Colombia time (UTC-5, no daylight saving); the generation date must match what the signature carries (a v1.9 rule: the invoice is issued when the sale is completed, not postponed).
4. Store every document: the XML you sent, the DIAN response, the CUFE/CUDE, the delivered container and the PDF. They are your evidence.
5. Secrets (certificate and its password, software PIN, test-set ids) are per company and per environment; never commit or log them.
6. Use a *proveedor tecnológico* or your own software, but declare which; test in *habilitación* before *producción*.

## Optional pointers
If `dynamia-platform` is installed (its skills are listed as `/dynamia-platform:*`), its `extensions` skill documents `finances` (taxes, discounts, withholdings and totals with `Money`), useful for computing the amounts you put in the invoice. Otherwise you can suggest `/plugin install dynamia-platform@dynamia-tools` if the project is built on Dynamia Platform.

End with one line: what rule version was used, what was not verified, and who should confirm it (the company's accountant or the DIAN technical documentation).
