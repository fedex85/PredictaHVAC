// Orden de ejemplo equivalente a la de core/test_sin_conexion.py::test_resumen_de_referencia (equipo SPLIT).
import { crearTrabajo } from '../core/static/sinconexion/trabajo.js';

export const TEXTOS = [
  ['INS_FILTROS', 'INSPECCION', 'Estado de los filtros'],
  ['INS_BATERIA', 'INSPECCION', 'Estado de la batería y del serpentín'],
  ['INS_FIJACIONES', 'INSPECCION', 'Fijaciones y soportes en buen estado'],
  ['INS_AISLAMIENTO', 'INSPECCION', 'Aislamiento de las tuberías en buen estado'],
  ['INS_LIMPIEZA', 'INSPECCION', 'Limpieza general del equipo'],
  ['INS_INTERIOR', 'INSPECCION', 'Limpieza de la unidad interior'],
  ['FUN_ARRANQUE', 'FUNCIONAMIENTO', 'Señal de arranque y contactor-compresor correctos'],
  ['FUN_VENTILACION', 'FUNCIONAMIENTO', 'Ventilación correcta'],
  ['FUN_CONDENSADOS', 'FUNCIONAMIENTO', 'Evacuación de condensados correcta'],
  ['FUN_ESTABLE', 'FUNCIONAMIENTO', 'Funcionamiento estable, sin vibraciones anómalas'],
  ['FUN_FUGAS', 'FUNCIONAMIENTO', 'Sin fugas visibles de refrigerante ni de aceite'],
];
export const MEDICIONES = [
  ['T_IMPULSION', 'Temperatura de impulsión', '°C', '-20.00', '80.00'],
  ['T_RETORNO', 'Temperatura de retorno', '°C', '-20.00', '80.00'],
  ['TENSION', 'Tensión', 'V', '0.00', '500.00'],
  ['CORRIENTE', 'Corriente', 'A', '0.00', '500.00'],
  ['P_ALTA', 'Presión alta', 'bar', '0.00', '60.00'],
  ['P_BAJA', 'Presión baja', 'bar', '0.00', '60.00'],
];

export function paquete(extra = {}) {
  return {
    orden: { id: 7, codigo: 'OT-7', estado: 'ASIGNADA', con_checklist: true, con_evidencias: true,
             subsanacion_motivo: '', subsanacion_bloque: '', requiere_refrigerante: false },
    equipo: { codigo: 'SP-1', nombre: 'Split', ubicacion: 'Sala', tipo: 'SPLIT' },
    catalogo: {
      puntos: TEXTOS.map(([codigo, bloque, texto]) => ({ codigo, bloque, texto })),
      mediciones: MEDICIONES.map(([codigo, etiqueta, unidad, minimo, maximo]) => ({ codigo, etiqueta, unidad, minimo, maximo })),
      mediciones_elegibles: [],
    },
    estado_actual: { puntos: [], mediciones: [], observaciones: '', materiales: '', sin_materiales: false, fotos: 0, firma: false },
    limites: { fotos_min: 3, fotos_max: 20, foto_bytes: 10485760 },
    descargada_en: '2026-10-12T10:00:00.000Z',
    ...extra,
  };
}

export const nuevoTrabajo = (extra) => crearTrabajo(paquete(extra), 3);
export const AHORA = new Date('2026-10-12T11:00:00.000Z');
