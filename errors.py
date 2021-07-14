import sys
from argparse import ArgumentParser
from collections import namedtuple
from functools import partial


error = namedtuple('error', 'header type msg short')
error_mapping = {
        0x0001: error("eError_BattShutdown", "Akku und RelayStatus", "Akku ist ausgeschaltet", "Akku ist ausgeschaltet"),
        0x0002: error("eError_UnderVoltProtection", "Akku und RelayStatus", "Entlade-/Unterspannungsrelay hat ausgelöst (redutierter Ladestrom!)", "Unterspannung"),
        0x0004: error("eError_OverVoltProtection", "Akku und RelayStatus", "Lade- /Überspannungsrelay hat ausgelöst (reduzierter Entladestrom!)", "Überspannungssicherung"),
        0x0008: error("eError_RelayUnitError", "Akku und RelayStatus", "Fehler in der Relaiseinheit (Kontakt- oder Diodenfehler)", "Kontakt/Diodenfehler"),
        # 0x000F: error("eError_BattStateMask", "Akku und RelayStatus", "Maske für Akku Status Meldungen"),
        0x0010: error("eError_UnderVoltage", "SpannungsFehler", "Unterspannungsfehler (bitte laden)", "Unterspannungsfehler"),
        0x0020: error("eError_OverVoltage", "SpannungsFehler", "Überspannungsfehler", "Ladungsabschaltung"),
        # 0x00F0: error("eError_VoltageErrorMask", "SpannungsFehler", "Maske für Spannungsfehler"),
        0x0100: error("eError_OverLoadCurrent", "Stromfehler", "Ladestrom überschritten", "Ladestrom überschritten"),
        0x0200: error("eError_OverDischargeCurrent", "Stromfehler", "Entladestrom überschritten", "Entladestrom überschritten"),
        0x0400: error("eError_ShortCircuit", "Stromfehler", "Kurzschlussfehler", "Kurzschlussfehler"),
        0x0800: error("eError_AutoResetFailed", "Stromfehler", "Auto Wiederzuschaltung hat nicht funktioniert (keine weiteren Zuschaltversuche)", "Auto-Reset Fehler"),
        # 0x0F00: error("eError_CurrentErrorMask", "Stromfehler", "Maske für Stromfehler"),
        0x1000: error("eError_ChargeTempLimit", "Temperaturfehler", "Akku hat Ladetemperatur unterschritten (nur noch Entladung möglich)", "Ladetemperatur unterschritten"),
        0x2000: error("eError_UnderTemp", "Temperaturfehler", "Akku untere Temperaturgrenze unterschritten (Ladung abgeschaltet)", "Ladetemperatur zu niedrig"),
        0x4000: error("eError_OverTemp", "Temperaturfehler", "Akku obere Temperaturgrenze überschritten (Abschaltung)", "Übertemperaturabschaltung"),
        # 0x7000: error("eError_TempErrorMask", "Temperaturfehler", "Maske für Temperaturfehler"),
        0x8000: error("eError_ExtBatteryError", "Fehler Ext. Akku", "Fehler externer Akku (nicht genauer spezifiziert)", "Externer Akku Fehler"),
    }
error_topics = list(error_mapping.keys())
error_types = {err.type for err in error_mapping.values()}
default_error_topics = set(error_topics) - {0x2, 0x4}


def parse_error(errorid):
    return [(eid, msg) for eid, msg in error_mapping.items() if eid & errorid]


def selector(error_id, error, err_topics, err_types):
    if not err_topics:
        err_topics = default_error_topics
    if not err_types:
        err_types = error_types
    return error_id in err_topics and error.type in err_types


def get_msg(errorid, err_topics=None, err_types=None):
    sel = partial(selector, err_topics=err_topics, err_types=err_types)
    return '\r\n'.join(err.msg for eid, err in parse_error(errorid) if sel(eid, err))


def get_short(errorid, err_topics=None, err_types=None):
    sel = partial(selector, err_topics=err_topics, err_types=err_types)
    return '\r\n'.join(err.short for eid, err in parse_error(errorid) if sel(eid, err))


def get_header(errorid, err_topics=None, err_types=None):
    sel = partial(selector, err_topics=err_topics, err_types=err_types)
    return '\r\n'.join(err.header.replace('eError_', '') for eid, err in parse_error(errorid) if sel(eid, err))


def get_all(errorid, err_topics=None, err_types=None):
    sel = partial(selector, err_topics=err_topics, err_types=err_types)
    return '\r\n'.join(f'{err.type} | {err.short}' for eid, err in parse_error(errorid) if sel(eid, err))


if __name__ == '__main__':
    parser = ArgumentParser(description='Script um errorcodes zu parsen.')
    parser.add_argument('errorid', type=int, help='Der Fehlercode')
    parser.add_argument('type', choices='header msg short all'.split(), help='short|header|msg|all')
    args = parser.parse_args()
    if args.type == 'header':
        print(get_header(args.errorid))
    elif args.type == 'msg':
        print(get_msg(args.errorid))
    elif args.type == 'short':
        print(get_short(args.errorid))
    elif args.type == 'all':
        print('Fehlercode | Typ | Kurz')
        print(get_all(args.errorid))
