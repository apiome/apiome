# FIX Orchestra 1.0 repository schema (vendored)

The official FIX Orchestra **v1.0 Technical Standard** repository XSD (namespace
`http://fixprotocol.io/2020/orchestra/repository`), copied unchanged from
[FIXTradingCommunity/fix-orchestra](https://github.com/FIXTradingCommunity/fix-orchestra) at tag `v1.6`
(commit `68ce876068aae1352b483ed8a41f1da3e3f9ea17`), `repository/src/main/resources/xsd/`:

- `repository.xsd`, `repositorytypes.xsd`: the Orchestra repository schema;
- `dc.xsd`, `dcterms.xsd`, `dcmitype.xsd`, `xml.xsd`: the Dublin Core and XML namespace schemas it imports.

Licensed under the Apache License 2.0 by FIX Trading Community. The FIX Orchestra export (MFX-37.1, #4323,
`app/fix_orchestra_emitter.py`) is validated against it; offline, no network access needed.
