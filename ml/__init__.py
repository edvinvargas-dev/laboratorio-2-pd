"""Paquete de modelado de NovaMercado: features, modelos, costo y entrenamiento.

Lo usan tanto el DAG de Airflow (entrenamiento) como la API (predicción), para que
las features se calculen exactamente igual en los dos lados.
"""
