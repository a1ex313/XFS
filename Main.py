import sys
import re
import datetime
from bitstring import BitArray


# Считываем данные суперблока
def read_superblock(filename):
    # Открыли файл для чтения в бинарном виде
    with open(filename, "rb") as f:
        # 2 байта содержащие размер сектора равный размеру суперблока
        f.seek(102)
        sb_sectsize = int.from_bytes(f.read(2), byteorder='big')

    # Считываем Суперблок
    with open(filename, "rb") as f:
        super_block = f.read(sb_sectsize)

    # Считываем данные из суперблока
    sb_blocksize = int.from_bytes(super_block[4:8], byteorder='big')        # Размер блока
    sb_agblocks = int.from_bytes(super_block[84:88], byteorder='big')       # Размер AG (в блоках)
    sb_inodesize = int.from_bytes(super_block[104:106], byteorder='big')    # Размер инф. узла(inode) (в байтах)
    sb_inopblock = int.from_bytes(super_block[106:108], byteorder='big')    # Количество инф. узлов в блоке
    sb_icount = int.from_bytes(super_block[128:136], byteorder='big')       # Кол-во выделенных инф. узлов
    sb_ifree = int.from_bytes(super_block[136:144], byteorder='big')        # Кол-во свободных инф. узлов
    used_inode = sb_icount - sb_ifree                                       # Кол-во заполненных инф. узлов
    sb_agcount = int.from_bytes(super_block[88:92], byteorder='big')        # Кол-во AG
    allocation_group_size = sb_blocksize * sb_agblocks                      # Размер AG (в байтах)

    '''
    Для того, чтобы найти правильный адресс нужного блока (в нашем случае адреса инф. узлов и журнала записей каталога)
    необходимо знать не только "абслоютный" адресс из суперблока, но также и "относительный" или же relative offset
    Для его нахождения нам понадобятся поля содержащие log2(AG size) - 124 байт и log2(inode/block) - 123 байт
    В нашем случае log2(AG size) = 16 и log2(inode/block) = 3
    Считаем sb_logstart как массив битов и представим его в двоичной форме:
    0x0000000000020006 - 0000000000000000000000000000000000000000000000100000000000000110 - 64 бита
    16 младших битов будут составлять относительный сдвиг, а оставшиеся старшие биты будут указывать на номер AG,
    в котором располагается нужный блок
    0000000000000110 и 00...010
    Переводим в десятичный вид и получаем 6 и 2. Это значит что у нас сдвиг журнала на 2 AG и еще на 6 блоков.
    (2 * AG_size(В блоках) + 6) * (размер блока в байтах) - адрес первого журнала
    
    С инф. узлом похожим образом: Считываем корневой узел sb_rootino и представляем его в бинарном виде:
    0000000000000000000000000000000000000000000000000000000010000000
    В данном случае нам нужно смотреть на по log2(AG size), а по сумме log2(AG size) и log2(inode/block) т.е. 19 бит
    0000000000010000000 - относительный сдвиг в бинарном виде или же 128, сдвиг по AG равен 0
    Относительное расположение инф узла в XFS — это целая часть относительного сдвига, деленное 
    на количество индексных дескрипторов в блоке. В нашем  случае это 128/8 или блок 16. Смещение инф. узла 
    в этом блоке равно 128 mod 8, что равно 0.
    (0 * AG_size(В блоках) + 16) * (размер блока в байтах) + (0 * размер инф. узла)- адрес первого инф. узла
    '''

    # Находим первый блок журнала
    sb_agblklog = int.from_bytes(super_block[124:125], byteorder='big')         # log2(размер AG) округленный вверх
    sb_logstart_bits = BitArray(bytes=super_block[48:56])
    ag_offset_bin = sb_logstart_bits.bin[:len(sb_logstart_bits) - sb_agblklog]  # Сдвиг по AG  битовом виде
    ag_offset = int(ag_offset_bin, 2)                                           # Сдвиг по AG
    relative_offset_bin = sb_logstart_bits.bin[-sb_agblklog:]                   # Относительный сдвиг журанала в битовом виде
    relative_offset = int(relative_offset_bin, 2)                               # Относительный сдвиг журанала
    sb_logstart = (ag_offset * sb_agblocks + relative_offset) * sb_blocksize    # Адресс журнала в байтах

    # Находем первый блок инф. узла
    sb_inopblog = int.from_bytes(super_block[123:124], byteorder='big')         # log2(инф. узел / блок)
    sb_rootino = int.from_bytes(super_block[56:64], byteorder='big')            # Номер инф. узла корневого каталога
    sb_rootino_bit = BitArray(bytes=super_block[56:64]).bin
    ag_offset_rootino_bit = sb_rootino_bit[:len(sb_rootino_bit) -               # Сдвиг по AG
                                            (sb_inopblog + sb_agblklog)]        # в битовом виде
    ag_offset_rootino = int(ag_offset_rootino_bit, 2)                           # Сдвиг по AG
    relative_offset_rootino_bit = sb_rootino_bit[-(sb_inopblog                  # Относительный сдвиг инф. узла
                                                   + sb_agblklog):]             # в битовом виде
    relative_offset_rootino = int(relative_offset_rootino_bit, 2)               # Относительный сдвиг инф. узла
    relative_block = int(relative_offset_rootino / sb_inopblock)
    relative_inode = relative_offset_rootino % sb_inopblock
    sb_rootino_start = ((ag_offset_rootino * sb_agblocks + relative_block)      # Адрес первого инф. узла
                        * sb_blocksize) + (relative_inode * sb_inodesize)

    string = "{:{fill}{align}{width}}"
    print("Характеристика Суперблока")
    print(string.format("Размер блока в байтах", width=50, align='<', fill=' '), sb_blocksize)
    print(string.format("Размер AG в блоках", width=50, align='<', fill=' '), sb_agblocks)
    print(string.format("Размер инф. узла в байтах", width=50, align='<', fill=' '), sb_inodesize)
    print(string.format("Номер инф. узла корневого каталога", width=50, align='<', fill=' '), sb_rootino)
    print(string.format("Количество инф. узлов в блоке", width=50, align='<', fill=' '), sb_inopblock)
    print(string.format("Кол-во выделенных инф. узлов", width=50, align='<', fill=' '), sb_icount)
    print(string.format("Кол-во свободных инф. узлов", width=50, align='<', fill=' '), sb_ifree)
    print(string.format("Кол-во заполненных инф. узлов", width=50, align='<', fill=' '), used_inode)
    print(string.format("Кол-во AG", width=50, align='<', fill=' '), sb_agcount)
    print(string.format("Размер AG (в байтах)", width=50, align='<', fill=' '), allocation_group_size)
    print(string.format("Адресс внутреннего журнала(логов)", width=50, align='<', fill=' '), sb_logstart)
    print(string.format("Адресс первого инф. узла", width=50, align='<', fill=' '), sb_rootino_start)
    return allocation_group_size, sb_agcount, sb_inodesize, used_inode, sb_sectsize, sb_blocksize, sb_rootino_start, sb_logstart


def check_access_mode(line):
    if line == "000":
        return "---"
    elif line == "001":
        return "--x"
    elif line == "010":
        return "-w-"
    elif line == "011":
        return "-wx"
    elif line == "100":
        return "r--"
    elif line == "101":
        return "r-x"
    elif line == "110":
        return "rw-"
    elif line == "111":
        return "rwx"


def check_format(line):
    if line == "000":
        return "Cпециальный файл (устройство)"
    elif line == "001":
        return "Каталог короткого формата или символьная ссылка"
    elif line == "010":
        return "Карта блоков (для каталогов, простых файлов и симв.ссылок)"
    elif line == "011":
        return "Би-дерево карты блоков (для каталогов и простых файлов) "
    elif line == "100":
        return "MNT: di_uuid"

'''
96 bytes on a V4 filesystem and 176 bytes on a V5 filesystem - ядро
После идет 4 байта di_next_unlinked
Затем идет short form dir 
'''
def read_inodes(filename, sb_rootino_start, sb_inodesize, used_inode):
    with open(filename, "rb") as f:
        f.seek(sb_rootino_start)
        if f.read(16).startswith(b"IN"):
            f.seek(sb_rootino_start)
            for i in range(used_inode):
                inode_start_pos = sb_rootino_start + i * sb_inodesize
                # Читаем данный инф. узел
                inode = f.read(sb_inodesize)
                di_ino = int.from_bytes(inode[152:160], byteorder="big")            # Номер инф. узла
                di_mode_file_type = BitArray(bytes=inode[2:4]).bin[0:4]             # Тип файла
                di_mode_access_mode = BitArray(bytes=inode[2:4]).bin[7:16]          # Режим доступа для
                access_mode_owner = check_access_mode(di_mode_access_mode[0:3])     # 1) Владельца
                access_mode_group = check_access_mode(di_mode_access_mode[3:6])     # 2) Группы
                access_mode_others = check_access_mode(di_mode_access_mode[6:9])   # 3) Остальных пользователей
                di_version = int.from_bytes(inode[4:5], byteorder="big")        # Версия инф. узла
                di_format_bin = BitArray(bytes=inode[5:6]).bin[5:8]             # Формат второй части инф.узла
                di_format = check_format(di_format_bin)
                di_uid = int.from_bytes(inode[8:12], byteorder="big")           # UID файла (идентификатор пользователя)
                di_gid = int.from_bytes(inode[12:16], byteorder="big")          # GID файла (идентификатор группы)
                di_nlink = int.from_bytes(inode[16:20], byteorder="big")        # v2+ количество ссылок
                di_atime = datetime.datetime.fromtimestamp(int.from_bytes(inode[32:36], byteorder="big")).strftime(
                    '%Y-%m-%d %H:%M:%S')                                        # Последний доступ к файлам
                di_mtime = datetime.datetime.fromtimestamp(int.from_bytes(inode[40:44], byteorder="big")).strftime(
                    '%Y-%m-%d %H:%M:%S')                                        # Последее изменение файла
                di_ctime = datetime.datetime.fromtimestamp(int.from_bytes(inode[48:52], byteorder="big")).strftime(
                    '%Y-%m-%d %H:%M:%S')                                        # Последнее изменение статуса инф. узла
                di_crtime = datetime.datetime.fromtimestamp(int.from_bytes(inode[144:148], byteorder="big")).strftime(
                    '%Y-%m-%d %H:%M:%S')                                        # Создание файла
                di_size = int.from_bytes(inode[56:64], byteorder="big")         # Размер файла (data fork) в байтах
                di_nblocks = int.from_bytes(inode[64:72], byteorder="big")      # Количество блоков в (data fork)
                di_nextents = int.from_bytes(inode[76:80], byteorder="big")     # Кол-во используемых экстентов данных
                di_anextents = int.from_bytes(inode[80:82], byteorder="big")    # Кол-во расширенных экстентов атрибута
                di_forkoff = int.from_bytes(inode[82:83], byteorder="big")      # Смещение инф. узла до xattr
                di_aformat = int.from_bytes(inode[83:84], byteorder="big")      # Флаг расширенного типа атрибута
                di_flag = int.from_bytes(inode[90:92], byteorder="big")         # Флаги
                di_gen = int.from_bytes(inode[92:96], byteorder="big")          # Номер поколения для идентификации

                string = "{:{fill}{align}{width}}"
                print("\n")
                print("Характеристика инф. узла/индексного дескриптора")
                print(string.format("Номер инф. узла", width=50, align='<', fill=' '), di_ino)
                print(string.format("Режим доступа для Владельца", width=50, align='<', fill=' '),
                      access_mode_owner)
                print(string.format("Режим доступа для Группы", width=50, align='<', fill=' '), access_mode_group)
                print(string.format("Режим доступа для Остальных пользователей", width=50, align='<', fill=' '),
                      access_mode_others)
                print(string.format("Версия инф. узла", width=50, align='<', fill=' '), di_version)
                print(string.format("Формат второй части инф.узла", width=50, align='<', fill=' '), di_format)
                print(string.format("UID файла (идентификатор пользователя)", width=50, align='<', fill=' '),
                      di_uid)
                print(string.format("GID файла (идентификатор группы)", width=50, align='<', fill=' '),
                      di_gid)
                print(string.format("v2+ количество ссылок", width=50, align='<', fill=' '), di_nlink)
                print(string.format("Время последнего доступа к файлам", width=50, align='<', fill=' '),
                      di_atime)
                print(string.format("Время последее изменения файла", width=50, align='<', fill=' '),
                      di_mtime)
                print(string.format("Время последнего изменения статуса инф. узла", width=50,
                                    align='<', fill=' '), di_ctime)
                print(string.format("Время создания файла", width=50, align='<', fill=' '), di_crtime)
                print(string.format("Размер файла (data fork) в байтах", width=50, align='<', fill=' '), di_size)
                print(string.format("Количество блоков в data fork", width=50, align='<', fill=' '),
                      di_nblocks)
                print(string.format("Кол-во используемых экстентов данных", width=50, align='<', fill=' '),
                      di_nextents)
                print(string.format("Кол-во расширенных экстентов атрибута", width=50, align='<', fill=' '),
                      di_anextents)
                print(string.format("Флаг расширенного типа атрибута", width=50, align='<', fill=' '), di_aformat)
                print(string.format("Флаги", width=50, align='<', fill=' '), di_flag)
                print(string.format("Номер поколения для идентификации", width=50, align='<', fill=' '), di_gen)
                print("\n")



def identify_logitem(line):
    if (line[0:2] == b'\x4E\x49'):
        print("inode_core")
    elif (line[0:2] == b'\x3C\x12'):
        print("buffer_log")
    elif (line[0:2] == b'\x3B\x12'):
        print("inode_update")
    elif (line[0:2] == b'\x3F\x12'):
        print("inode_creation")
    elif (line[0:2] == b'\x36\x12'):
        print("efi")
    elif (line[0:2] == b'\x37\x12'):
        print("efd")


    if (line[0:4] == b'\x4E\x41\x52\x54'):
        print('Transaction header')
    elif (line[0:4] == b'\x58\x41\x47\x49'):
        print('AGI')
    elif (line[0:4] == b'\x49\x41\x42\x33'):
        print('Inode b+ tree')
    elif (line[0:4] == b'\x58\x46\x53\x42'):
        print('Superblock')
    elif (line[0:4] == b'\x58\x41\x47\x46'):
        print('AG free')
    elif (line[0:4] == b'\x41\x42\x33\x43'):
        print('Free b+tree count')
    elif (line[0:4] == b'\x41\x42\x33\x42'):
        print('Free b+tree offset')



def read_journal(filename, sb_logstart):
    with open(filename, "rb") as f:
        # Начало журнала
        f.seek(sb_logstart)
        while True:

            # Открываем журнал

            if f.read(4).startswith(b"\xfe\xed\xba\xbe"):
                f.seek(-4, 1)
                header_log = f.read(512)
                h_len = int.from_bytes(header_log[12:16], byteorder='big')          # Длина записи журнала в байтах
                if h_len == 0:
                    break
                h_cycle = int.from_bytes(header_log[4:8], byteorder="big")          # Номер цикла этой записи журнала
                h_version = int.from_bytes(header_log[8:12], byteorder="big")       # Версия записи журнала
                '''Порядковые номера журналов представляют собой 64-битную величину, состоящую из двух 32-битных 
                величин. Старшие 32 бита — это «номер цикла», который увеличивается каждый раз, когда XFS просматривает 
                журнал. Младшие 32 бита — это «номер блока», который назначается при фиксации транзакции и
                должен соответствовать смещению блока в журнале.'''
                h_lsn = int.from_bytes(header_log[16:24], byteorder="big")          # Порядковый номер этой записи
                                                                                    # в журнале
                h_tail_lsn = int.from_bytes(header_log[24:32], byteorder="big")     #Порядковый номер первой записи
                                                                                    # журнала с
                                                                                    # незафиксированными буферами
                h_crc = int.from_bytes(header_log[32:36], byteorder="big")          #Контрольная сумма заголовка записи
                                                                                    # журнала, данных цикла и
                                                                                    # самих записей журнала
                h_prev_block = int.from_bytes(header_log[36:40], byteorder="big")   # Номер блока предыдущей
                                                                                    # записи журнала
                h_num_logops = int.from_bytes(header_log[40:44], byteorder='big')   # Количество операций журнала
                                                                                    # в этой записи
                h_cycle_data = int.from_bytes(header_log[44:48], byteorder="big")   #
                h_fmt = int.from_bytes(header_log[48:52], byteorder="big")          # Формат записи журнала
                h_fs_uuid = int.from_bytes(header_log[52:68], byteorder="big")      # UUID файловой системы
                h_size = int.from_bytes(header_log[68:72], byteorder="big")         # Размер записи внутреннего журнала

                xlog_op = f.read(h_len)
                i = 0
                remaining = h_len
                # Check if trans. ID exists
                while (int.from_bytes(xlog_op[i:i + 5], byteorder='big') != 0):
                    if (xlog_op[i + 4:i + 8] == b'\x00\x00\x00\x01'):
                        oh_len = 128
                    else:
                        oh_len = int.from_bytes(xlog_op[i + 4:i + 8], byteorder='big')  # Кол-во байтов в области данных
                    oh_clientid = xlog_op[i + 8:i + 9]                                  # Автор этой операции
                    oh_flags = xlog_op[i + 9:i + 10]                                # Флаги, связанные с этой операцией
                    # Make sure remaining data are still enough
                    remaining = remaining - 12
                    if (oh_len > remaining):
                        break
                    # XFS_TRANSACTION: Operation came from a transaction
                    # if (oh_clientid == b'\x69'):
                    if (oh_flags == b'\x01'):
                        print('Start a new transaction')
                    elif (oh_flags == b'\x02'):
                        print('Commit this transaction\n')
                        is_shortformdir = False
                    else:
                        xlog_item = xlog_op[i + 12:i + 12 + oh_len]
                        identify_logitem(xlog_item)
                    # Move to next log item
                    i = i + 12 + oh_len





if __name__ == "__main__":
    allocation_group_size, sb_agcount, sb_inodesize, used_inode, sb_sectsize, sb_blocksize, sb_rootino_start, sb_logstart = read_superblock("file.img")
    read_inodes("file.img", sb_rootino_start, sb_inodesize, used_inode)
    #read_journal("file.img", sb_logstart)
    