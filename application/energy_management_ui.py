import os

from nicegui import ui, app
from datetime import datetime, timedelta
from dotenv import load_dotenv
from services.database_service import DBService, HeatpumpAction
from services.sonnen_battery_service import SonnenBatteryService
from services.goe_service import GoEService
from services.wago_energy_meter import WagoEnergyMeter
from services.sgready_device_service import SGReadyDeviceService
from services.panasonic_aquarea_service import PanasonicAquareaService
from services.bmw_cardata_service import BMWCarDataService

load_dotenv()
db_service = DBService(db_path=os.getenv("DATABASE_PATH"), energy_status_retention_minutes=int(os.getenv("SONNEN_ENERGY_STATUS_RETENTION")))
sonnen_battery_service = SonnenBatteryService(db_service, host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"), non_used_energy_buffer=int(os.getenv("NON_USED_ENERGY_BUFFER", 500)))
goe_service = GoEService(host=os.getenv("GOE_HOST"), api_key=os.getenv("GOE_API_KEY"), fixed_charging_user=int(os.getenv("GOE_FIXED_CHARGING_USER")), dynamic_charging_user=int(os.getenv("GOE_DYNAMIC_CHARGING_USER")))
energy_meter = WagoEnergyMeter(port=os.getenv("ENERGY_METER_PORT"), slave_id=int(os.getenv("ENERGY_METER_SLAVE_ID")), baudrate=int(os.getenv("ENERGY_METER_BAUDRATE")))
ww_heatpump_service = SGReadyDeviceService(db_service, int(os.getenv("RELAY_PIN_WW")), "Weishaupt Warm Water Heatpump", int(os.getenv("WW_ENERGY_CONSUMPTION")))
heating_heatpump_service = PanasonicAquareaService(db_service, int(os.getenv("RELAY_PIN_HEATING1")), int(os.getenv("RELAY_PIN_HEATING2")), "Panasonic Heating Heatpump", int(os.getenv("HEATING1_ENERGY_CONSUMPTION")), int(os.getenv("HEATING2_ENERGY_CONSUMPTION")))
bmw_cardata_service = BMWCarDataService(db_service=db_service, vin=os.getenv("BMW_VIN"), client_id=os.getenv("BMW_CLIENT_ID"), streaming_topic=os.getenv("BMW_STREAMING_TOPIC"))

STOP_CAR_CHARGING_WAIT_TIME = int(os.getenv("STOP_CAR_CHARGING_WAIT_TIME"))
GRID_FEED_IN_MOVING_AVERAGE_INTERVAL = int(os.getenv("GRID_FEED_IN_MOVING_AVERAGE_INTERVAL", 20))
BATTERY_FEED_IN_MOVING_AVERAGE_INTERVAL = int(os.getenv("BATTERY_FEED_IN_MOVING_AVERAGE_INTERVAL", 5))
CAR_CHARGING_MOVING_AVERAGE_INTERVAL = int(os.getenv("CAR_CHARGING_MOVING_AVERAGE_INTERVAL", 5))

def request_token():
    token = bmw_cardata_service.dcf_step3_request_access_token()
    if token:
        ui.notify("Token request successful", type="positive")
    else:
        ui.notify("Token request failed", type="negative")

class EnergyManagementUI:
    def __init__(self):
        self.db_service = db_service
        self.sonnen_battery_service = sonnen_battery_service

    def run(self):
        app.add_static_files("/static", "static")
        ui.run(title="Energy Status Dashboard", favicon="static/energy_status_dashboard.ico")
               
    @ui.page("/")
    def main_page():
        # do not refresh - but rely on the updates of the main loop of the application.
        sonnen_battery_service.refresh_status(update_db = False)  # Refresh the status to get the latest data

        ui.add_head_html('<link rel="apple-touch-icon" href="static/apple-touch-icon.png">')        
        with ui.grid(columns="10px 150px auto").style("padding: 10px;"):
            # Car Charging
            ui.label("Car Charging").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")
            
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("User").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            (user_id, user_name) = goe_service.get_last_user_with_name()
            ui.label(f"{user_name} (ID: {user_id})").style("font-size: 16px; margin-top: 0px;")
            
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Service status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            charging_status = db_service.get_goe_status()
            ui.label(f"{charging_status.action.label} (since {charging_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Charger status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            charger_status = goe_service.get_charger_status()
            ui.label(f"{charger_status.label}").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Car status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            car_status = goe_service.get_car_status()
            ui.label(f"{car_status.label}").style("font-size: 16px; margin-top: 0px;")
            
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Power").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            power = energy_meter.get_current_power_kw()
            ui.label(f"{power} kW").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("PV surplus enabled").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            pv_enabled = goe_service._is_pv_surplus_enabled()
            logic_mode = goe_service.get_logic_mode()
            ui.label("Yes" if pv_enabled else "No").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Logic mode").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            logic_mode = goe_service.get_logic_mode()
            ui.label(f"{logic_mode.label}").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Configured phases / current").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ph = goe_service.get_phases()
            phases = "autom." if ph == 0 else str(ph)
            current = goe_service.get_charging_current()
            ui.label(f"{phases} / {current} A").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Charger error").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            charger_error = goe_service.get_error()
            ui.label(f"{charger_error.label}").style("font-size: 16px; margin-top: 0px;")
            
            # Car Status
            ui.label("Car Status").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")

            if bmw_cardata_service.is_access_token_valid() or bmw_cardata_service.is_refresh_token_valid():
                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("Mileage").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                mileage_data = bmw_cardata_service.get_mileage()
                if mileage_data is not None:
                    mileage, unit, timestamp = mileage_data
                else:
                    mileage, unit, timestamp = None, None, None
                if mileage is not None and unit is not None and timestamp is not None:
                    ui.label(f"{int(mileage):,.0f} {unit} (since {timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
                else:
                    ui.label("n/a").style("font-size: 16px; margin-top: 0px;")
                
                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("Battery level").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                battery_level_data = bmw_cardata_service.get_battery_charge_level()
                if battery_level_data is not None:
                    level, unit, timestamp = battery_level_data
                else:
                    level, unit, timestamp = None, None, None
                if level is not None and unit is not None and timestamp is not None:
                    ui.label(f"{level} {unit} (since {timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
                else:
                    ui.label("n/a").style("font-size: 16px; margin-top: 0px;")
                
                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("Battery delta fully charged").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                battery_delta_data = bmw_cardata_service.get_battery_delta_fully_charged()
                if battery_delta_data is not None:
                    delta_fully_charged, unit, timestamp = battery_delta_data
                else:
                    delta_fully_charged, unit, timestamp = None, None, None
                if delta_fully_charged is not None and unit is not None and timestamp is not None:
                    ui.label(f"{delta_fully_charged} {unit} (since {timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
                else:
                    ui.label("n/a").style("font-size: 16px; margin-top: 0px;")

                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("Remaining range").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                remaining_range_data = bmw_cardata_service.get_remaining_range()
                if remaining_range_data is not None:
                    remaining_range, unit, timestamp = remaining_range_data
                else:
                    remaining_range, unit, timestamp = None, None, None
                if remaining_range is not None and unit is not None and timestamp is not None:
                    ui.label(f"{int(remaining_range):,.0f} {unit} (since {timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
                else:
                    ui.label("n/a").style("font-size: 16px; margin-top: 0px;")                
            else:
                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("DCF Step 2").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                verification_uri = bmw_cardata_service.dcf_step2_get_verification_uri()
                if verification_uri:
                    ui.link(verification_uri, verification_uri, new_tab=True).style("font-size: 16px; margin-top: 0px;")
                else:
                    ui.label("DCF workflow not started yet").style("font-size: 16px; margin-top: 0px;")

                ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                ui.label("DCF Step 3").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
                # ui.label("Request token").style("font-size: 16px; margin-top: 0px;")
                ui.button("Request token", on_click=request_token) \
                    .props("flat dense no-caps") \
                    .classes("text-blue-700 underline p-0 min-h-0")

            # Sonnen Battery
            ui.label("Sonnen Battery").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Battery level").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            battery_level = sonnen_battery_service.get_battery_level()
            ui.label(f"{battery_level} %").style("font-size: 16px; margin-top: 0px;")
            
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Discharging allowed").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            discharging_allowed = not sonnen_battery_service.is_discharge_disabled()
            ui.label("Yes" if discharging_allowed else "No").style("font-size: 16px; margin-top: 0px;")
        
            # WW Heatpump
            ui.label(f"{ww_heatpump_service.name}").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ww_status = db_service.get_heatpump_status_by_id(ww_heatpump_service.get_id())
            ui.label(f"{ww_status.action.label} (since {ww_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
        
            # Heating Heatpump
            ui.label(f"{heating_heatpump_service.name}").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            heating_status = db_service.get_heatpump_status_by_id(heating_heatpump_service.get_id())
            ui.label(f"{heating_status.action.label} (since {heating_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
            
        with ui.header(elevated=True).style("background-color: #f0f0f0; padding: 10px;").classes("items-center justify-between"):
            ui.label("Energy Status Dashboard").style("font-size: 24px; font-weight: bold;color :#333;")
            
            energy_status = sonnen_battery_service.get_energy_status_with_available_power_time_series(120, moving_average_interval=GRID_FEED_IN_MOVING_AVERAGE_INTERVAL, battery_average_interval=BATTERY_FEED_IN_MOVING_AVERAGE_INTERVAL, car_charging_average_interval=CAR_CHARGING_MOVING_AVERAGE_INTERVAL)
            if energy_status:
                # get list of production values from energy_status
                timestamps = [status.timestamp for status in energy_status]
                energy_productions = [status.production / 1000 for status in energy_status]
                energy_consumptions = [status.consumption / 1000 for status in energy_status]
                energy_feed_in = [status.feed_in / 1000 for status in energy_status]
                battery_feed_in = [status.battery_feed_in / 1000 for status in energy_status]
                avg_battery_feed_in = [status.average_battery_feed_in / 1000 for status in energy_status]
                car_charging = [(status.car_charging or 0) / 1000 for status in energy_status]
                avg_car_charging = [(status.average_car_charging or 0) / 1000 for status in energy_status]
                available_power = [status.average_available_power / 1000 for status in energy_status]

                fig = {
                    "data": [
                        {
                            "x": timestamps,
                            "y": energy_productions, 
                            "type": "scatter",
                            "mode": "lines",
                            "name": "Prod.", 
                            "line": {"color": "#f3cf03"},
                            "fill": "tozeroy",
                            "fillcolor": "rgba(243, 207, 3, 0.1)"
                        },
                        {"x": timestamps, "y": energy_consumptions, "type": "scatter", "mode": "lines", "name": "Cons.", "line": {"color": "#4355fab7"}},
                        {"x": timestamps, "y": energy_feed_in, "type": "scatter", "mode": "lines", "name": "Feed-in", "line": {"color": "#505050"}},
                        {"x": timestamps, "y": battery_feed_in, "type": "scatter", "mode": "lines", "name": "Battery", "line": {"color": "#50d81b"}},
                        {"x": timestamps, "y": avg_battery_feed_in, "type": "scatter", "mode": "lines", "name": "Avg. B.", "line": {"color": "rgba(93, 217, 109, 0.4)"}}, # {"color": "#53cf2263"}},
                        {"x": timestamps, "y": car_charging, "type": "scatter", "mode": "lines", "name": "Car", "line": {"color": "#ff6600"}},
                        {"x": timestamps, "y": avg_car_charging, "type": "scatter", "mode": "lines", "name": "Avg. Car", "line": {"color": "rgba(255, 102, 0, 0.3)"}},
                        {
                            "x": timestamps,
                            "y": available_power,
                            "type": "scatter",
                            "mode": "lines",
                            "name": "Avg. Avl.",
                            "line": {"color": "rgba(80, 80, 80, 0.2)"},
                            "fill": "tozeroy",
                            "fillcolor": "rgba(202, 202, 201, 0.2)"
                        },
                    ],
                    "layout": {
                        "margin": {"t": 0, "r": 0, "b": 14, "l": 40},
                        "plot_bgcolor": "#f8f8f8",
                        "paper_bgcolor": "#f0f0f0",
                        "xaxis": {
                            "tickfont": {"size": 10}
                        },
                        "yaxis": {
                            "title": {"text": "Power (kW)", "font": {"size": 10}},
                            "tickfont": {"size": 10}
                        },
                        "legend": {
                            "font": {"size": 10},
                        }
                    },
                    "config": {
                        "staticPlot": True,
                        "displayModeBar": False,
                        "displaylogo": False
                    }
                }
                ui.plotly(fig).style("width: 100%; height: 170px; background-color: #f0f0f0; border: 0px solid #ddd; border-radius: 0px; padding: 0px;")
            else:
                ui.label("No energy data available").style("color: #666;")
            
        with ui.footer(elevated=True).style("background-color: #f0f0f0; padding: 10px;").classes("items-center justify-between"):
            # Fetch current energy production from the database
            energy_production = sonnen_battery_service.get_energy_production() / 1000
            energy_consumption = sonnen_battery_service.get_energy_consumption() / 1000
            available_energy = sonnen_battery_service.get_grid_feed() / 1000
            available_energy_avg = sonnen_battery_service.get_grid_feed_in_average(GRID_FEED_IN_MOVING_AVERAGE_INTERVAL) / 1000
            
            ui.label(f"Production: {energy_production} kW").style("color: #666;font-size: 10pt;")
            ui.label(f"Consumption: {energy_consumption} kW").style("color: #666;font-size: 10pt;")
            ui.label(f"Grid feed-in: {available_energy} kW").style("color: #666;font-size: 10pt;")
            ui.label(f"Avg. grid feed-in ({GRID_FEED_IN_MOVING_AVERAGE_INTERVAL} min): {available_energy_avg:.3f} kW").style("color: #666;font-size: 10pt;")