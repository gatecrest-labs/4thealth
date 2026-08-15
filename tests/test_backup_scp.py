from pathlib import Path
from unittest.mock import MagicMock, patch

CFG = {
    'enabled': True,
    'protocol': 'scp',
    'host': '10.0.0.1',
    'port': 22,
    'username': 'user',
    'password': 'secret',
    'remote_dir': '/backups',
}


def test_transfer_file_scp_connects_and_puts(tmp_path):
    local_file = tmp_path / 'backup.zip'
    local_file.write_bytes(b'data')

    mock_ssh = MagicMock()
    mock_transport = MagicMock()
    mock_ssh.get_transport.return_value = mock_transport

    mock_scpc = MagicMock()
    mock_scpc.__enter__ = MagicMock(return_value=mock_scpc)
    mock_scpc.__exit__ = MagicMock(return_value=False)

    with patch('paramiko.SSHClient', return_value=mock_ssh), \
         patch('scp.SCPClient', return_value=mock_scpc):
        from app.backup_scheduler import transfer_file
        transfer_file(CFG, str(local_file))

    mock_ssh.connect.assert_called_once_with(
        '10.0.0.1', port=22, username='user', password='secret', timeout=30
    )
    mock_scpc.put.assert_called_once_with(str(local_file), '/backups/backup.zip')
    mock_ssh.close.assert_called_once()


def test_test_connection_scp_returns_ok():
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_ssh.open_sftp.return_value = mock_sftp
    # sftp.stat() returns normally (no exception)

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        from app.backup_scheduler import test_connection
        result = test_connection(CFG)

    assert result.get('success') is True
    assert 'Connected to' in result.get('message', '')
    mock_ssh.connect.assert_called_once_with(
        '10.0.0.1', port=22, username='user', password='secret', timeout=30
    )
    mock_sftp.stat.assert_called_once_with('/backups')
    mock_sftp.close.assert_called_once()
    mock_ssh.close.assert_called_once()


def test_test_connection_scp_bad_dir_returns_error():
    mock_ssh = MagicMock()
    mock_sftp = MagicMock()
    mock_sftp.stat.side_effect = IOError('No such file')
    mock_ssh.open_sftp.return_value = mock_sftp

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        from app.backup_scheduler import test_connection
        result = test_connection(CFG)

    assert result.get('success') is False
    assert result.get('message')
    mock_ssh.close.assert_called_once()
