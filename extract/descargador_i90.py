import requests
import pandas as pd
import zipfile
import os
import math
import pytz
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Union
from tqdm import tqdm
import sys
import os

# Add the project root to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from utilidades.db_utils import DatabaseUtils
from configs.i90_config import I90Config, TerciariaConfig, SecundariaConfig, RRConfig, CurtailmentConfig, P48Config

class I90DownloaderDL:
    """
    Class for downloading and processing I90 files from ESIOS API.
    
    This class handles:
    - Downloading I90 files from ESIOS API
    - Extracting and processing the data from the Excel files
    - Applying time adjustments for special days (23/25 hours)
    - Filtering data by programming units and markets
    """
    
    def __init__(self):
        """Initialize the I90 downloader with ESIOS API token"""
        self.esios_token = os.getenv('ESIOS_API_KEY')
        self.config = I90Config()
        self.lista_errores = self.config.get_error_data()
        self.temporary_download_path = self.config.temporary_download_path

    def get_i90_data(self, day: datetime, sheets_of_interest: List[str]) -> pd.DataFrame:
        """
        Get I90 data for a specific day.
        
        Args:
            day (datetime): The specific day to retrieve data for
            sheets_of_interest (List[str]): List of sheet IDs to process
            
        Returns:
            pd.DataFrame: Processed data from the I90 file
        """
        # Download the file
        zip_file_name, excel_file_name = self._make_i90_request(day)
        
        # Get error data for the day
        df_errores_dia = self.lista_errores[self.lista_errores['fecha'] == day.date()]

        #if there are errors for that particular day
        if not df_errores_dia.empty:
            pestañas_con_error = df_errores_dia['tipo_error'].values
            # Filter out sheets with errors
            valid_sheets = [sheet for sheet in sheets_of_interest if int(sheet) not in pestañas_con_error]

            if not valid_sheets:
                print(f"Warning: All requested sheets have errors for {day.date()}")
                return pd.DataFrame()
        
        # Process the file with valid sheets only
        filtered_excel_file = self.process_sheet(excel_file_name, valid_sheets)

        # Clean up files
        self.cleanup_files(zip_file_name, excel_file_name)
        
        return filtered_excel_file
    
    def _make_i90_request(self, day: datetime) -> Tuple[str, str]:
        """
        Download I90 file for a specific day from ESIOS API.
        
        Args:
            day (datetime): Day to download data for
            
        Returns:
            Tuple[str, str]: File names for the downloaded and extracted files
        """
        # Construct API URL for the I90 file
        address = f"https://api.esios.ree.es/archives/34/download?date_type\u003ddatos\u0026end_date\u003d{day.date()}T23%3A59%3A59%2B00%3A00\u0026locale\u003des\u0026start_date\u003d{day.date()}T00%3A00%3A00%2B00%3A00"
        
        # Download the file
        resp = requests.get(
            address, 
            headers={
                'x-api-key': self.esios_token,
                'Authorization': f'Token token={self.esios_token}'
            }
        )
        
        # Save the downloaded file
        with open(f"{self.temporary_download_path}/{day.date()}.zip", "wb") as fd:
            fd.write(resp.content)
        
        # Create file names for the downloaded and extracted files
        zip_file_name = f"{day.year}-{str(day.month).zfill(2)}-{str(day.day).zfill(2)}"
        excel_file_name = f"{day.year}{str(day.month).zfill(2)}{str(day.day).zfill(2)}"
        
        # Extract the zip file
        with zipfile.ZipFile(f"{self.temporary_download_path}/{zip_file_name}.zip", 'r') as zip_ref:
            zip_ref.extractall(self.temporary_download_path)
        
        return zip_file_name, excel_file_name
    
    def process_sheet(self, excel_file_name: str, sheets_to_keep: List[str]) -> pd.ExcelFile:
        """
        Process the I90 Excel file by filtering and keeping only specified sheets.
        
        Args:
            file_name_2 (str): Base name of the Excel file to process
            sheets_to_keep (List[str]): List of sheet names to keep (e.g. ['03', '05', '07']), have to pass 
            str and zero padded (e.g. '03' instead of 3)
            
        Returns:
            pd.ExcelFile: Processed Excel file containing only specified sheets
            
        Notes:
            - Creates a new filtered Excel file with only the specified sheets
            - Original file remains unchanged
        """
        # Load the Excel file
        excel_file = pd.ExcelFile(f"{self.temporary_download_path}/I90DIA_{excel_file_name}.xls")
        
        # Get all sheet names in the file
        all_sheets = excel_file.sheet_names
        
        # Create a list of sheet names to keep with proper formatting
        target_sheets = [f'I90DIA{sheet}' for sheet in sheets_to_keep]
        
        # Filter sheets
        filtered_sheets = [sheet for sheet in all_sheets if sheet in target_sheets]
        
        # Create a new Excel file with only the filtered sheets
        writer = pd.ExcelWriter(f"{self.temporary_download_path}/I90DIA_{excel_file_name}_filtered.xls", engine='openpyxl')
        
        # Copy selected sheets to new file
        for sheet in filtered_sheets:
            df = pd.read_excel(excel_file, sheet_name=sheet)
            df.to_excel(writer, sheet_name=sheet, index=False)
        
        # Save and close the writer
        writer.close()
        
        # Return the new filtered Excel file
        return pd.ExcelFile(f"{self.temporary_download_path}/I90DIA_{excel_file_name}_filtered.xls")
    
    def cleanup_files(self, zip_file_name: str, excel_file_name: str) -> None:
        """
        Clean up temporary files after processing.
        
        Args:
            file_name (str): Base file name for the zip file
            file_name_2 (str): Base file name for the Excel file
        """
        # Remove the downloaded and extracted files
        os.remove(f"./{zip_file_name}.zip")
        os.remove(f"./I90DIA_{excel_file_name}.xls")
    



    def process_sheet_v1(self, pestaña: int, file_name_2: str, unidades: List[str], 
                      df_mercados: pd.DataFrame, pestañas_volumenes: List[int],
                      is_special_date: bool, tipo_cambio_hora: int, day: datetime) -> List[Tuple[pd.DataFrame, str, bool]]:
        """
        Process data from a specific sheet in the I90 file.
        
        Args:
            pestaña (int): Sheet ID to process
            file_name_2 (str): Base file name for the Excel file
            unidades (List[str]): List of programming unit names to filter data for
            df_mercados (pd.DataFrame): DataFrame with market data
            pestañas_volumenes (List[int]): List of sheet IDs for volume data
            is_special_date (bool): Whether the day is a special date (23 or 25 hours)
            tipo_cambio_hora (int): Timezone offset for the day
            day (datetime): Day being processed
            
        Returns:
            List[Tuple[pd.DataFrame, str, bool]]: List of tuples with processed DataFrames, market names, and price flags
        """
        # Special handling for sheet 5 after SRS start date
        if pestaña == 5 and day >= self.dia_inicio_SRS:
            return []
        
        # Define sheet name format and load data
        sheet = str(pestaña).zfill(2)
        
        # Different skiprows depending on sheet
        if sheet not in ['03', '05', '06', '07', '08', '09', '10']:
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=3)
        else:
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=2)
        
        # Handle special case for sheet 05
        if sheet == '05' and 'Participante del Mercado' in df.columns:
            df = df.rename(columns={'Participante del Mercado': 'Unidad de Programación'})
        
        # Filter by programming units
        df = df[df['Unidad de Programación'].isin(unidades)]
        
        # Determine if this is a volume or price sheet
        is_precio = pestaña not in pestañas_volumenes
        
        # Filter markets based on sheet type
        if pestaña in pestañas_volumenes:
            df_mercados_filtrado = df_mercados[df_mercados['sheet_i90_volumenes'] == pestaña]
        else:
            df_mercados_filtrado = df_mercados[df_mercados['sheet_i90_precios'] == pestaña]
        
        # Copy dataframe for processing
        df_sheet = df.copy()
        results = []
        
        # Process each market in the sheet
        for _, mercado in df_mercados_filtrado.iterrows():
            # Create a fresh copy of the data
            df = df_sheet.copy()
            
            # Apply direction filter if specified
            if mercado['sentido'] == 'Subir':
                df = df[df['Sentido'] == 'Subir']
            elif mercado['sentido'] == 'Bajar':
                df = df[df['Sentido'] == 'Bajar']
            
            # Apply specific filters based on sheet
            if sheet == '03':
                if mercado['mercado'] in ['Curtailment', 'Curtailment demanda']:
                    df = df[df['Redespacho'].isin(['UPLPVPV', 'UPLPVPCBN', 'UPOPVPB'])]
                elif mercado['mercado'] in ['RT2 a subir', 'RT2 a bajar']:
                    df = df[df['Redespacho'].isin(['ECOBSO', 'ECOBCBSO'])]
                else:
                    df = df[df['Redespacho'].isin(['ECO', 'ECOCB', 'UPOPVPV', 'UPOPVPVCB'])]

            elif sheet == '07':
                if mercado['mercado'] in ['Terciaria a subir', 'Terciaria a bajar']:
                    df = df[df['Redespacho'] != 'TERDIR']
                else:
                    df = df[df['Redespacho'] == 'TERDIR']

            elif sheet == '08' or sheet == '10':
                if mercado['mercado'] == "Indisponibilidades":
                    df = df[df['Redespacho'] == "Indisponibilidad"]
                else:
                    df = df[df['Redespacho'] == "Restricciones Técnicas"]

            elif sheet == '09':
                df = df[df['Redespacho'].isin(['ECO', 'ECOCB', 'UPOPVPV', 'UPOPVPVCB'])]
            
            # Filter columns to keep only programming unit and value columns
            total_col = df.columns.get_loc("Total")
            cols_to_drop = list(range(0, total_col+1))
            up_col = df.columns.get_loc("Unidad de Programación")
            cols_to_drop.remove(up_col)
            df = df.drop(df.columns[cols_to_drop], axis=1)
            
            # Melt the dataframe to convert from wide to long format
            hora_colname = df.columns[1]
            df = df.melt(id_vars=["Unidad de Programación"], var_name="hora", value_name="valor")
            
            # Apply time adjustments based on special dates and format
            if len(df) > 0:
                if hora_colname == 1:
                    if mercado['is_quinceminutal']:
                        df['hora'] = df.apply(self.ajuste_quinceminutal, axis=1, 
                                             is_special_date=is_special_date, 
                                             tipo_cambio_hora=tipo_cambio_hora)
                    else:
                        df['hora'] = df.apply(self.ajuste_quinceminutal_a_horario, axis=1, 
                                             is_special_date=is_special_date, 
                                             tipo_cambio_hora=tipo_cambio_hora)
                else:
                    df['hora'] = df.apply(self.ajuste_horario, axis=1, 
                                         is_special_date=is_special_date, 
                                         tipo_cambio_hora=tipo_cambio_hora)
                
                # Aggregate data
                if is_precio:
                    df = df.groupby(['Unidad de Programación', 'hora']).mean().reset_index()
                    df['valor'] = df['valor'].round(decimals=3)
                else:
                    df = df.groupby(['Unidad de Programación', 'hora']).sum().reset_index()
                    df = df[df['valor'] != 0.0]
                
                # Add date and market ID
                df['fecha'] = day
                df['id_mercado'] = mercado['id']
                
                # Get UP_id from Unidad de Programación
                df = df.rename(columns={"Unidad de Programación": "UP"})
                
                # Save the processed data
                results.append((df, mercado['mercado'].lower(), is_precio))
        
        return results
    

class TerciariaVolumenDL(I90DownloaderDL):
    """
    Specialized class for downloading and processing tertiary regulation volume data from I90 files.
    """
    
    def __init__(self):
        """Initialize the tertiary regulation downloader"""
        super().__init__()

        #initialize config
        self.config = TerciariaConfig()

        #get sheets of interest
        self.sheets_of_interest = self.config.sheets_of_interest

    def get_i90_data(self, day: datetime) -> pd.DataFrame:
        """
        Get I90 data for a specific day.
        """
        return super().get_i90_data(day, self.sheets_of_interest)
        
    def get_volumenes(self, day: datetime, bbdd_engine, UP_ids: Optional[List[int]] = None, 
                    sentidos: Optional[List[str]] = None) -> List[Tuple[pd.DataFrame, str]]:
        """
        Get tertiary regulation volume data for a specific day.
        
        Args:
            day (datetime): Day to download data for
            bbdd_engine: Database engine connection
            UP_ids (Optional[List[int]]): List of programming unit IDs to filter
            sentidos (Optional[List[str]]): List of directions to filter ['Subir', 'Bajar', 'Directa']
            
        Returns:
            List[Tuple[pd.DataFrame, str]]: List of tuples with (DataFrame, direction)
        """
        # Set default sentidos if None
        if sentidos is None:
            sentidos = ['Subir', 'Bajar', 'Directa']
        
        # Get Programming Units
        unidades, dict_unidades = self.get_programming_units(bbdd_engine, UP_ids)
        
        # Download I90 file
        file_name, file_name_2 = self.download_i90_file(day)
        
        # Get transition dates
        filtered_transition_dates = self.get_transition_dates(day, day + timedelta(days=1))
        day_datef = day.date()
        is_special_date = day_datef in filtered_transition_dates
        tipo_cambio_hora = filtered_transition_dates.get(day_datef, 0)
        
        # Get error data
        df_errores = self.get_error_data(bbdd_engine)
        df_errores_dia = df_errores[df_errores['fecha'] == day.date()]
        pestañas_con_error = df_errores_dia['tipo_error'].values
        
        results = []
        
        # Check if the sheet has errors
        if self.sheet_id not in pestañas_con_error:
            sheet = str(self.sheet_id).zfill(2)
            
            # Load sheet data
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=2)
            
            # Filter by programming units
            df = df[df['Unidad de Programación'].isin(unidades)]
            
            # Process for each direction
            for sentido in sentidos:
                df_sentido = df.copy()
                
                # Apply direction filter
                if sentido == 'Subir':
                    df_sentido = df_sentido[df_sentido['Sentido'] == 'Subir']
                    df_sentido = df_sentido[df_sentido['Redespacho'] != 'TERDIR']
                elif sentido == 'Bajar':
                    df_sentido = df_sentido[df_sentido['Sentido'] == 'Bajar']
                    df_sentido = df_sentido[df_sentido['Redespacho'] != 'TERDIR']
                elif sentido == 'Directa':
                    df_sentido = df_sentido[df_sentido['Redespacho'] == 'TERDIR']
                
                # Filter columns to keep only programming unit and value columns
                if not df_sentido.empty:
                    total_col = df_sentido.columns.get_loc("Total")
                    cols_to_drop = list(range(0, total_col+1))
                    up_col = df_sentido.columns.get_loc("Unidad de Programación")
                    cols_to_drop.remove(up_col)
                    df_sentido = df_sentido.drop(df_sentido.columns[cols_to_drop], axis=1)
                    
                    # Melt the dataframe to convert from wide to long format
                    hora_colname = df_sentido.columns[1]
                    df_sentido = df_sentido.melt(id_vars=["Unidad de Programación"], var_name="hora", value_name="volumen")
                    
                    # Apply time adjustments
                    if hora_colname == 1:
                        df_sentido['hora'] = df_sentido.apply(self.ajuste_quinceminutal, axis=1, 
                                                             is_special_date=is_special_date, 
                                                             tipo_cambio_hora=tipo_cambio_hora)
                    else:
                        df_sentido['hora'] = df_sentido.apply(self.ajuste_horario, axis=1, 
                                                             is_special_date=is_special_date, 
                                                             tipo_cambio_hora=tipo_cambio_hora)
                    
                    # Aggregate data
                    df_sentido = df_sentido.groupby(['Unidad de Programación', 'hora']).sum().reset_index()
                    df_sentido = df_sentido[df_sentido['volumen'] != 0.0]
                    
                    # Add date and rename columns
                    df_sentido['fecha'] = day
                    df_sentido = df_sentido.rename(columns={"Unidad de Programación": "UP"})
                    
                    # Add UP_id from dict_unidades
                    df_sentido['UP_id'] = df_sentido['UP'].map(dict_unidades)
                    
                    # Store the result
                    results.append((df_sentido, sentido))
        
        # Clean up files
        self.cleanup_files(file_name, file_name_2)
        
        return results

class SecundariaVolumenDL(I90DownloaderDL):
    """
    Specialized class for downloading and processing secondary regulation volume data from I90 files.
    """
    
    def __init__(self):
        """Initialize the secondary regulation downloader"""
        super().__init__()

        #initialize config
        self.config = SecundariaConfig()

        #get sheets of interest
        self.sheets_of_interest = self.config.sheets_of_interest
        
    def get_volumenes(self, day: datetime, bbdd_engine, UP_ids: Optional[List[int]] = None, 
                    sentidos: Optional[List[str]] = None) -> List[Tuple[pd.DataFrame, str]]:
        """
        Get secondary regulation volume data for a specific day.
        
        Args:
            day (datetime): Day to download data for
            bbdd_engine: Database engine connection
            UP_ids (Optional[List[int]]): List of programming unit IDs to filter
            sentidos (Optional[List[str]]): List of directions to filter ['Subir', 'Bajar']
            
        Returns:
            List[Tuple[pd.DataFrame, str]]: List of tuples with (DataFrame, direction)
        """
        # Set default sentidos if None
        if sentidos is None:
            sentidos = ['Subir', 'Bajar']
        
        # Get Programming Units
        unidades, dict_unidades = self.get_programming_units(bbdd_engine, UP_ids)
        
        # Download I90 file
        file_name, file_name_2 = self.download_i90_file(day)
        
        # Get transition dates
        filtered_transition_dates = self.get_transition_dates(day, day + timedelta(days=1))
        day_datef = day.date()
        is_special_date = day_datef in filtered_transition_dates
        tipo_cambio_hora = filtered_transition_dates.get(day_datef, 0)
        
        # Get error data
        df_errores = self.get_error_data(bbdd_engine)
        df_errores_dia = df_errores[df_errores['fecha'] == day.date()]
        pestañas_con_error = df_errores_dia['tipo_error'].values
        
        results = []
        
        # Check if the sheet has errors
        if self.sheet_id not in pestañas_con_error:
            sheet = str(self.sheet_id).zfill(2)
            
            # Load sheet data
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=2)
            
            # Filter by programming units
            df = df[df['Unidad de Programación'].isin(unidades)]
            
            # Process for each direction
            for sentido in sentidos:
                df_sentido = df.copy()
                
                # Apply direction filter
                if sentido == 'Subir':
                    df_sentido = df_sentido[df_sentido['Sentido'] == 'Subir']
                elif sentido == 'Bajar':
                    df_sentido = df_sentido[df_sentido['Sentido'] == 'Bajar']
                
                # Filter columns to keep only programming unit and value columns
                if not df_sentido.empty:
                    total_col = df_sentido.columns.get_loc("Total")
                    cols_to_drop = list(range(0, total_col+1))
                    up_col = df_sentido.columns.get_loc("Unidad de Programación")
                    cols_to_drop.remove(up_col)
                    df_sentido = df_sentido.drop(df_sentido.columns[cols_to_drop], axis=1)
                    
                    # Melt the dataframe to convert from wide to long format
                    hora_colname = df_sentido.columns[1]
                    df_sentido = df_sentido.melt(id_vars=["Unidad de Programación"], var_name="hora", value_name="volumen")
                    
                    # Apply time adjustments
                    if hora_colname == 1:
                        df_sentido['hora'] = df_sentido.apply(self.ajuste_quinceminutal, axis=1, 
                                                             is_special_date=is_special_date, 
                                                             tipo_cambio_hora=tipo_cambio_hora)
                    else:
                        df_sentido['hora'] = df_sentido.apply(self.ajuste_horario, axis=1, 
                                                             is_special_date=is_special_date, 
                                                             tipo_cambio_hora=tipo_cambio_hora)
                    
                    # Aggregate data
                    df_sentido = df_sentido.groupby(['Unidad de Programación', 'hora']).sum().reset_index()
                    df_sentido = df_sentido[df_sentido['volumen'] != 0.0]
                    
                    # Add date and rename columns
                    df_sentido['fecha'] = day
                    df_sentido = df_sentido.rename(columns={"Unidad de Programación": "UP"})
                    
                    # Add UP_id from dict_unidades
                    df_sentido['UP_id'] = df_sentido['UP'].map(dict_unidades)
                    
                    # Store the result
                    results.append((df_sentido, sentido))
        
        # Clean up files
        self.cleanup_files(file_name, file_name_2)
        
        return results

class RRVolumenDL(I90DownloaderDL):
    """
    Specialized class for downloading and processing Replacement Reserve (RR) volume data from I90 files.
    """
    
    def __init__(self):
        """Initialize the RR downloader"""
        super().__init__()
        self.sheet_id = 8  # Sheet 08 contains RR data
        
    def get_volumenes(self, day: datetime, bbdd_engine, UP_ids: Optional[List[int]] = None) -> pd.DataFrame:
        """
        Get RR volume data for a specific day.
        
        Args:
            day (datetime): Day to download data for
            bbdd_engine: Database engine connection
            UP_ids (Optional[List[int]]): List of programming unit IDs to filter
            
        Returns:
            pd.DataFrame: DataFrame with RR volume data
        """
        # Get Programming Units
        unidades, dict_unidades = self.get_programming_units(bbdd_engine, UP_ids)
        
        # Download I90 file
        file_name, file_name_2 = self.download_i90_file(day)
        
        # Get transition dates
        filtered_transition_dates = self.get_transition_dates(day, day + timedelta(days=1))
        day_datef = day.date()
        is_special_date = day_datef in filtered_transition_dates
        tipo_cambio_hora = filtered_transition_dates.get(day_datef, 0)
        
        # Get error data
        df_errores = self.get_error_data(bbdd_engine)
        df_errores_dia = df_errores[df_errores['fecha'] == day.date()]
        pestañas_con_error = df_errores_dia['tipo_error'].values
        
        result_df = pd.DataFrame()
        
        # Check if the sheet has errors
        if self.sheet_id not in pestañas_con_error:
            sheet = str(self.sheet_id).zfill(2)
            
            # Load sheet data
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=2)
            
            # Filter by programming units
            df = df[df['Unidad de Programación'].isin(unidades)]
            
            # Filter for RR data - exclude indisponibilidades
            df = df[df['Redespacho'] == 'Restricciones Técnicas']
            
            # Filter columns to keep only programming unit and value columns
            if not df.empty:
                total_col = df.columns.get_loc("Total")
                cols_to_drop = list(range(0, total_col+1))
                up_col = df.columns.get_loc("Unidad de Programación")
                cols_to_drop.remove(up_col)
                df = df.drop(df.columns[cols_to_drop], axis=1)
                
                # Melt the dataframe to convert from wide to long format
                hora_colname = df.columns[1]
                df = df.melt(id_vars=["Unidad de Programación"], var_name="hora", value_name="volumen")
                
                # Apply time adjustments
                if hora_colname == 1:
                    df['hora'] = df.apply(self.ajuste_quinceminutal, axis=1, 
                                         is_special_date=is_special_date, 
                                         tipo_cambio_hora=tipo_cambio_hora)
                else:
                    df['hora'] = df.apply(self.ajuste_horario, axis=1, 
                                         is_special_date=is_special_date, 
                                         tipo_cambio_hora=tipo_cambio_hora)
                
                # Aggregate data
                df = df.groupby(['Unidad de Programación', 'hora']).sum().reset_index()
                df = df[df['volumen'] != 0.0]
                
                # Add date and rename columns
                df['fecha'] = day
                df = df.rename(columns={"Unidad de Programación": "UP"})
                
                # Add UP_id from dict_unidades
                df['UP_id'] = df['UP'].map(dict_unidades)
                
                result_df = df
        
        # Clean up files
        self.cleanup_files(file_name, file_name_2)
        
        return result_df

class CurtailmentVolumenDL(I90DownloaderDL):
    """
    Specialized class for downloading and processing curtailment volume data from I90 files.
    """
    
    def __init__(self):
        """Initialize the curtailment downloader"""
        super().__init__()
        self.sheet_id = 3  # Sheet 03 contains curtailment data
        
    def get_volumenes(self, day: datetime, bbdd_engine, UP_ids: Optional[List[int]] = None,
                     tipos: Optional[List[str]] = None) -> List[Tuple[pd.DataFrame, str]]:
        """
        Get curtailment volume data for a specific day.
        
        Args:
            day (datetime): Day to download data for
            bbdd_engine: Database engine connection
            UP_ids (Optional[List[int]]): List of programming unit IDs to filter
            tipos (Optional[List[str]]): List of curtailment types to filter ['Curtailment', 'Curtailment demanda']
            
        Returns:
            List[Tuple[pd.DataFrame, str]]: List of tuples with (DataFrame, curtailment type)
        """
        # Set default tipos if None
        if tipos is None:
            tipos = ['Curtailment', 'Curtailment demanda']
        
        # Get Programming Units
        unidades, dict_unidades = self.get_programming_units(bbdd_engine, UP_ids)
        
        # Download I90 file
        file_name, file_name_2 = self.download_i90_file(day)
        
        # Get transition dates
        filtered_transition_dates = self.get_transition_dates(day, day + timedelta(days=1))
        day_datef = day.date()
        is_special_date = day_datef in filtered_transition_dates
        tipo_cambio_hora = filtered_transition_dates.get(day_datef, 0)
        
        # Get error data
        df_errores = self.get_error_data(bbdd_engine)
        df_errores_dia = df_errores[df_errores['fecha'] == day.date()]
        pestañas_con_error = df_errores_dia['tipo_error'].values
        
        results = []
        
        # Check if the sheet has errors
        if self.sheet_id not in pestañas_con_error:
            sheet = str(self.sheet_id).zfill(2)
            
            # Load sheet data
            df = pd.read_excel(f"./I90DIA_{file_name_2}.xls", sheet_name=f'I90DIA{sheet}', skiprows=2)
            
            # Filter by programming units
            df = df[df['Unidad de Programación'].isin(unidades)]
            
            # Process for each tipo
            for tipo in tipos:
                df_tipo = df.copy()
                
                # Apply curtailment type filter
                if tipo == 'Curtailment':
                    df_tipo = df_tipo[df_tipo['Redespacho'].isin(['UPLPVPV', 'UPLPVPCBN'])]
                elif tipo == 'Curtailment demanda':
                    df_tipo = df_tipo[df_tipo['Redespacho'] == 'UPOPVPB']
                
                # Filter columns to keep only programming unit and value columns
                if not df_tipo.empty:
                    total_col = df_tipo.columns.get_loc("Total")
                    cols_to_drop = list(range(0, total_col+1))
                    up_col = df_tipo.columns.get_loc("Unidad de Programación")
                    cols_to_drop.remove(up_col)
                    df_tipo = df_tipo.drop(df_tipo.columns[cols_to_drop], axis=1)
                    
                    # Melt the dataframe to convert from wide to long format
                    hora_colname = df_tipo.columns[1]
                    df_tipo = df_tipo.melt(id_vars=["Unidad de Programación"], var_name="hora", value_name="volumen")
                    
                    # Apply time adjustments
                    if hora_colname == 1:
                        df_tipo['hora'] = df_tipo.apply(self.ajuste_quinceminutal, axis=1, 
                                                       is_special_date=is_special_date, 
                                                       tipo_cambio_hora=tipo_cambio_hora)
                    else:
                        df_tipo['hora'] = df_tipo.apply(self.ajuste_horario, axis=1, 
                                                       is_special_date=is_special_date, 
                                                       tipo_cambio_hora=tipo_cambio_hora)
                    
                    # Aggregate data
                    df_tipo = df_tipo.groupby(['Unidad de Programación', 'hora']).sum().reset_index()
                    df_tipo = df_tipo[df_tipo['volumen'] != 0.0]
                    
                    # Add date and rename columns
                    df_tipo['fecha'] = day
                    df_tipo = df_tipo.rename(columns={"Unidad de Programación": "UP"})
                    
                    # Add UP_id from dict_unidades
                    df_tipo['UP_id'] = df_tipo['UP'].map(dict_unidades)
                    
                    # Store the result
                    results.append((df_tipo, tipo))
        
        # Clean up files
        self.cleanup_files(file_name, file_name_2)
        
        return results
    
