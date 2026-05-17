import os
import sys
import zipfile
import json
import pytest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../backend')))

from agents.agent6_packager import package_documents, ZeroByteFileError

@pytest.fixture
def mock_documents_setup(tmp_path):
    """Cria arquivos temporários válidos para empacotamento."""
    docs_dir = tmp_path / "agent5_output"
    docs_dir.mkdir()
    
    files = {
        "proposta": ["proposta_comercial.pdf"],
        "documentacao": ["compatibilidade.docx", "checklist.pdf"],
        "administrativo": ["autorizacao.xlsx"]
    }
    
    file_paths = {}
    for folder, file_list in files.items():
        file_paths[folder] = []
        for file_name in file_list:
            fpath = docs_dir / file_name
            fpath.write_bytes(b"Dummy Content to avoid 0 bytes error")
            file_paths[folder].append(str(fpath))
            
    return file_paths, docs_dir

@pytest.mark.asyncio
async def test_agent6_packaging_success(mock_documents_setup, tmp_path):
    """Verifica a estrutura do ZIP, o manifest.json e a limpeza dos temporários."""
    file_paths, docs_dir = mock_documents_setup
    
    # Agente 7 (Jurídico) foi aprovado, incluímos um arquivo extra
    juridico_path = docs_dir / "impugnacao.pdf"
    juridico_path.write_bytes(b"Juridico content")
    file_paths["juridico"] = [str(juridico_path)]
    
    item_id = "04"
    output_dir = tmp_path / "final_zips"
    output_dir.mkdir()
    
    zip_path = await package_documents(item_id=item_id, categorized_files=file_paths, output_dir=str(output_dir))
    
    # Assert do nome do arquivo
    assert os.path.basename(zip_path) == f"licit_item_{item_id}_attivos.zip"
    
    # Verifica o conteúdo do ZIP
    with zipfile.ZipFile(zip_path, 'r') as zf:
        namelist = zf.namelist()
        
        # Assert das pastas
        assert any(name.startswith("proposta/") for name in namelist)
        assert any(name.startswith("documentacao/") for name in namelist)
        assert any(name.startswith("administrativo/") for name in namelist)
        assert any(name.startswith("juridico/") for name in namelist)
        
        # Assert do manifest
        assert "manifest.json" in namelist
        
        with zf.open("manifest.json") as manifest_file:
            manifest = json.loads(manifest_file.read().decode('utf-8'))
            assert "proposta/proposta_comercial.pdf" in manifest
            assert len(manifest["proposta/proposta_comercial.pdf"]) == 64  # SHA-256 hash length

    # A Regra do Desapego: arquivos temporários originais devem ter sido apagados
    assert not os.path.exists(file_paths["proposta"][0])
    assert not os.path.exists(juridico_path)

@pytest.mark.asyncio
async def test_agent6_packaging_zero_byte_error(mock_documents_setup, tmp_path):
    """Regra Absoluta: 0kb dispara erro crítico de integridade."""
    file_paths, docs_dir = mock_documents_setup
    
    # Insere um arquivo de 0 bytes na documentação
    zero_byte_path = docs_dir / "arquivo_corrompido.pdf"
    zero_byte_path.write_bytes(b"")  # 0 bytes
    file_paths["documentacao"].append(str(zero_byte_path))
    
    item_id = "05"
    output_dir = tmp_path / "final_zips"
    output_dir.mkdir()
    
    with pytest.raises(ZeroByteFileError) as exc_info:
        await package_documents(item_id=item_id, categorized_files=file_paths, output_dir=str(output_dir))
        
    assert "0 bytes" in str(exc_info.value).lower() or "0kb" in str(exc_info.value).lower()
