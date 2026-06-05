import json

from tools.cad_bim_extract_ifc import extract_ifc


def test_extract_ifc_builds_cad_bim_json(tmp_path):
    source = tmp_path / "sample.ifc"
    source.write_text(
        """
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCOWNERHISTORY($,$,$,$,$,$,$,$);
#2=IFCBUILDINGSTOREY('0123456789ABCDEabcde01',#1,'Level 01',$,$,$,$,$,$);
#3=IFCBUILDINGELEMENTPROXY('1123456789ABCDEabcde02',#1,'Pump',$,'Equipment',$,#10,'P-01');
#4=IFCPROPERTYSINGLEVALUE('FireRating',$,IFCLABEL('EI 60'),$);
#5=IFCPROPERTYSET('pset-guid',#1,'Pset_Test',$,(#4));
#6=IFCRELDEFINESBYPROPERTIES('rel-pset',#1,$,$,(#3),#5);
#7=IFCMATERIAL('Steel',$,$);
#8=IFCRELASSOCIATESMATERIAL('rel-mat',#1,$,$,(#3),#7);
#9=IFCRELCONTAINEDINSPATIALSTRUCTURE('rel-spatial',#1,$,$,(#3),#2);
#10=IFCPRODUCTDEFINITIONSHAPE($,$,());
ENDSEC;
END-ISO-10303-21;
""",
        encoding="utf-8",
    )

    payload = extract_ifc(source)

    assert payload["type"] == "IFCModel"
    assert payload["source_format"] == "ifc"
    assert payload["properties"]["schema"] == "IFC4"
    assert {item["id"] for item in payload["elements"]} == {"0123456789ABCDEabcde01", "1123456789ABCDEabcde02"}
    element = next(item for item in payload["elements"] if item["id"] == "1123456789ABCDEabcde02")
    assert element["material"] == "Steel"
    assert element["propertySets"]["Pset_Test"]["FireRating"]["value"] == "EI 60"
    text = json.dumps(payload, ensure_ascii=False)
    assert "spatial" in text
