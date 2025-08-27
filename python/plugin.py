
import json
import logging
import os
import sys
import zipfile
import requests
from typing import Dict, Optional, Any, Tuple
import time
import tempfile
from requests import Response
from urllib.parse import urlencode
import shutil
import subprocess
import webbrowser
from pathlib import Path
import ctypes
from ctypes import byref, windll, wintypes

# Data Types
Response = Dict[bool, Optional[str]]

CONFIG_FILE = os.path.join(
    os.environ.get("PROGRAMDATA", "."),
    "NVIDIA Corporation",
    "nvtopps",
    "rise",
    "plugins",
    "mrivals",
    "config.json"
)

LOG_FILE = os.path.join(os.environ.get("USERPROFILE", "."), 'mrivals_plugin.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Mod.io API Constants
MRIVALS_API_KEY = None


def main():
    ''' Main entry point.

    Sits in a loop listening to a pipe, waiting for commands to be issued. After
    receiving the command, it is processed and the result returned. The loop
    continues until the "shutdown" command is issued.

    Returns:
        0 if no errors occurred during execution; non-zero if an error occurred
    '''
    TOOL_CALLS_PROPERTY = 'tool_calls'
    CONTEXT_PROPERTY = 'messages'
    SYSTEM_INFO_PROPERTY = 'system_info'  # Added for game information
    FUNCTION_PROPERTY = 'func'
    PARAMS_PROPERTY = 'params'
    INITIALIZE_COMMAND = 'initialize'
    SHUTDOWN_COMMAND = 'shutdown'

    ERROR_MESSAGE = 'Plugin Error!'

    # Generate command handler mapping
    commands = {
        'initialize': execute_initialize_command,
        'shutdown': execute_shutdown_command,
        'mrivals_get_character_info': execute_get_character_info,
        'mrivals_get_player_stats': execute_get_player_stats
    }
    cmd = ''

    logging.info('Marvel Rivals Plugin started')
    while cmd != SHUTDOWN_COMMAND:
        response = None
        input = read_command()
        if input is None:
            logging.error('Error reading command')
            continue

        logging.info(f'Received input: {input}')

        if TOOL_CALLS_PROPERTY in input:
            tool_calls = input[TOOL_CALLS_PROPERTY]
            for tool_call in tool_calls:
                if FUNCTION_PROPERTY in tool_call:
                    cmd = tool_call[FUNCTION_PROPERTY]
                    logging.info(f'Processing command: {cmd}')
                    if cmd in commands:
                        if cmd in [INITIALIZE_COMMAND, SHUTDOWN_COMMAND]:
                            response = commands[cmd]()
                        else:
                            response = commands[cmd](tool_call[PARAMS_PROPERTY] if PARAMS_PROPERTY in tool_call else {})
                    else:
                        logging.warning(f'Unknown command: {cmd}')
                        response = generate_failure_response(f'{ERROR_MESSAGE} Unknown command: {cmd}')
                else:
                    logging.warning('Malformed input: missing function property')
                    response = generate_failure_response(f'{ERROR_MESSAGE} Malformed input.')
        else:
            logging.warning('Malformed input: missing tool_calls property')
            response = generate_failure_response(f'{ERROR_MESSAGE} Malformed input.')

        logging.info(f'Sending response: {response}')
        write_response(response)

        if cmd == SHUTDOWN_COMMAND:
            logging.info('Shutdown command received, terminating plugin')
            break

    logging.info('mrivals Plugin stopped.')
    return 0


def read_command() -> dict or None:
    try:
        STD_INPUT_HANDLE = -10
        pipe = windll.kernel32.GetStdHandle(STD_INPUT_HANDLE)
        chunks = []

        while True:
            BUFFER_SIZE = 4096
            message_bytes = wintypes.DWORD()
            buffer = bytes(BUFFER_SIZE)
            success = windll.kernel32.ReadFile(pipe, buffer, BUFFER_SIZE, byref(message_bytes), None)

            if not success:
                logging.error('Error reading from command pipe')
                return None

            chunk = buffer.decode('utf-8')[:message_bytes.value]
            chunks.append(chunk)

            if message_bytes.value < BUFFER_SIZE:
                break

        retval = ''.join(chunks)
        logging.info(f'Raw JSON string before parsing: {"".join(chunks)}')

        return json.loads(retval)

    except json.JSONDecodeError:
        try:
            raw_input = ''.join(chunks) if chunks else 'No data'
        except Exception as join_err:
            raw_input = f'Could not join chunks (error: {join_err}). Chunks list: {repr(chunks)}'
        logging.error(f'Failed to decode JSON input. Raw data: {repr(raw_input)}')
        return None
    except Exception as e:
        logging.error(f'Unexpected error in read_command: {str(e)}')
        return None

def write_response(response:Response) -> None:
    ''' Writes a response to the communication pipe.

    Args:
        response: Function response
    '''
    try:
        STD_OUTPUT_HANDLE = -11
        pipe = windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

        json_message = json.dumps(response) + '<<END>>'
        message_bytes = json_message.encode('utf-8')
        message_len = len(message_bytes)

        bytes_written = wintypes.DWORD()
        windll.kernel32.WriteFile(
            pipe,
            message_bytes,
            message_len,
            bytes_written,
            None
        )

    except Exception as e:
        logging.error(f'Failed to write response: {str(e)}')
        pass

def generate_failure_response(body:dict=None) -> dict:
    ''' Generates a response indicating failure.

    @param[in] data  information to be attached to the response

    @return dictionary response (to be converted to JSON when writing to the
    communications pipe)
    '''
    response = body.copy() if body is not None else dict()
    response['success'] = False
    return response

def generate_success_response(body:dict=None) -> dict:
    ''' Generates a response indicating success.

    @param[in] data  information to be attached to the response

    @return dictionary response (to be converted to JSON when writing to the
    communications pipe)
    '''
    response = body.copy() if body is not None else dict()
    response['success'] = True
    return response

def summarize_character(data: Dict[str, Any], fallback_name: str) -> str:
    """
    Build a short, voice-friendly summary from the API schema you provided:
      - name, real_name
      - role, attack_type, difficulty
      - team[]
      - bio/lore
      - first ability (if present)
    """
    name        = data.get("name") or fallback_name.title()
    real_name   = data.get("real_name")
    role        = data.get("role") or "Unknown role"
    attack_type = data.get("attack_type") or "unknown attack type"
    difficulty  = data.get("difficulty") or "unknown difficulty"
    team_list   = data.get("team") or []
    team        = ", ".join(team_list) if team_list else "no listed team"
    bio         = data.get("bio") or data.get("lore") or ""

    # Abilities
    ability_line = "No abilities listed."
    abilities = data.get("abilities") or []
    if isinstance(abilities, list) and abilities:
        a0 = abilities[0] if isinstance(abilities[0], dict) else {}
        abil_name = a0.get("name", "Unnamed ability")
        abil_desc = a0.get("description", "")
        ability_line = f"Their signature ability is '{abil_name}': {abil_desc}"

    parts = [
        f"{name}" + (f", also known as {real_name}" if real_name else ""),
        f"is a {role} hero using {attack_type} attacks on {team}, rated {difficulty} to play.",
        bio,
        ability_line
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())

def summarize_player_stats(data: Dict[str, Any], fallback_name: str) -> str:
    name = data.get("name")

    # format data into just player overall stats
    data = data.get("overall_stats")

    matches     = data.get("total_matches") or fallback_name.title()
    wins        = data.get("total_wins") or "unknown wins"

    # format data into unranked gameplay
    data = data.get("unranked")
    
    kills       = data.get("total_kills") or "unknown kills"
    assists     = data.get("total_assists") or "Unknown assists"
    deaths      = data.get("total_deaths") or "unknown deaths"
    time        = data.get("total_time_played") or "unknown time"
    mvp         = data.get("total_mvp") or "unknown mvp times"

    parts = [
        f"{name}" + (f", has played {str(matches)} toal matches."),
        (f"Their win rate is {100*(int(wins)/int(matches)):.1f}% with an average of {int(kills)/int(matches):.1f} kills per match, "),
        (f"{int(deaths)/int(matches):.1f} deaths per match, and {int(assists)/int(matches):.1f} assists per match. "),
        (f"{name} has been the match MVP {mvp} times. They have played Marvel Rivals for {time}.")
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def execute_initialize_command() -> dict:
    ''' Command handler for `initialize` function

    This handler is responseible for initializing the plugin.

    Args:
        params: Function parameters

    Returns:
        The function return value(s)
    '''
    logging.info('Initializing plugin')
    # initialization function body
    return generate_success_response('initialize success.')

def execute_shutdown_command() -> dict:
    ''' Command handler for `shutdown` function

    This handler is responsible for releasing any resources the plugin may have
    acquired during its operation (memory, access to hardware, etc.).

    Args:
        params: Function parameters

    Returns:
        The function return value(s)
    '''
    logging.info('Shutting down plugin')
    # shutdown function body
    return generate_success_response('shutdown success.')

def execute_get_character_info(params: dict = None) -> dict:
    # config
    logging.info('fetching api key from config file')
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            config = json.load(file)
            MRIVALS_API_KEY = config.get('api_key')

    if not MRIVALS_API_KEY:
        return generate_failure_response({ 'message': "Missing API key. Add 'api_key' to config.json next to the EXE." })

    character_name = None

    logging.info('getting character name from user query')
    if ('character_name' in params and params['character_name'] is not None):
        character_name = str(params['character_name'])
    else:
        character_name = 'ironman'
    

    try:
        logging.info(f'attempting api call with user-specified character name: {character_name}')
        url = f"https://marvelrivalsapi.com/api/v1/heroes/hero/{character_name}"
        headers = {"x-api-key": MRIVALS_API_KEY}
        resp = requests.get(url, headers=headers)

        if resp.status_code == 401:
            return generate_failure_response(
                { 'message': f'mrivals1 fail' }
            )
        if resp.status_code == 404:
            return generate_failure_response(
                { 'message': f'mrivals2 fail' }
            )
        if resp.status_code == 429:
            return generate_failure_response(
                { 'message': f'mrivals3 fail' }
            )
        if resp.status_code >= 500:
            return generate_failure_response(
                { 'message': f'mod.io API5 request failed' }
            )
        if resp.status_code != 200:
            return generate_failure_response(
                { 'message': f'mod.io API2 request failed' }
            )

        data = resp.json()
        summary = summarize_character(data, str(character_name))
        return generate_success_response({'message': f'Summary: {summary}'})

    except requests.Timeout:
        return generate_failure_response({ 'message': f'API Request timed out.' })
    except Exception as e:
        logging.error(f"Error fetching character info: {e}")
        return generate_failure_response({ 'message': f'Error retrieving character info: {e}' })

def execute_get_player_stats(params: dict = None) -> dict:
    # config
    logging.info('fetching api key from config file')
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            config = json.load(file)
            MRIVALS_API_KEY = config.get('api_key')

    if not MRIVALS_API_KEY:
        return generate_failure_response({ 'message': "Missing API key. Add 'api_key' to config.json next to the EXE." })

    player_name = None

    logging.info('getting stats from user query')
    if ('player_name' in params and params['player_name'] is not None):
        player_name = str(params['player_name'])
    else:
        player_name = 'jaddo11'
    

    try:
        logging.info(f'attempting api call with user-specified player name: {player_name}')
        url = f"https://marvelrivalsapi.com/api/v1/player/{player_name}"
        headers = {"x-api-key": MRIVALS_API_KEY}
        resp = requests.get(url, headers=headers)

        if resp.status_code == 401:
            return generate_failure_response(
                { 'message': f'mrivals1 fail' }
            )
        if resp.status_code == 404:
            return generate_failure_response(
                { 'message': f'mrivals2 fail' }
            )
        if resp.status_code == 429:
            return generate_failure_response(
                { 'message': f'mrivals3 fail' }
            )
        if resp.status_code >= 500:
            return generate_failure_response(
                { 'message': f'mrivals4 fails' }
            )
        if resp.status_code != 200:
            return generate_failure_response(
                { 'message': f'mrivals5 fails' }
            )

        data = resp.json()
        summary = summarize_player_stats(data, str(player_name))
        return generate_success_response({'message': f'Summary: {summary}'})

    except requests.Timeout:
        return generate_failure_response({ 'message': f'API Request timed out.' })
    except Exception as e:
        logging.error(f"Error fetching character info: {e}")
        return generate_failure_response({ 'message': f'Error retrieving character info: {e}' })


if __name__ == '__main__':
    logging.info("Starting mrivals plugin")
    main()