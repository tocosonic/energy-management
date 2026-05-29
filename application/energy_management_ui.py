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

load_dotenv()
db_service = DBService(db_path=os.getenv("DATABASE_PATH"))
sonnen_battery_service = SonnenBatteryService(db_service, host=os.getenv("SONNEN_BATTERY_HOST"), port=os.getenv("SONNEN_BATTERY_PORT"), api_key=os.getenv("SONNEN_BATTERY_API_KEY"))
goe_service = GoEService(host=os.getenv("GOE_HOST"), api_key=os.getenv("GOE_API_KEY"), fixed_charging_user=int(os.getenv("GOE_FIXED_CHARGING_USER")), dynamic_charging_user=int(os.getenv("GOE_DYNAMIC_CHARGING_USER")))
energy_meter = WagoEnergyMeter(port=os.getenv("ENERGY_METER_PORT"), slave_id=int(os.getenv("ENERGY_METER_SLAVE_ID")), baudrate=int(os.getenv("ENERGY_METER_BAUDRATE")))
ww_heatpump_service = SGReadyDeviceService(db_service, int(os.getenv("RELAY_PIN_WW")), "Weishaupt Warm Water Heatpump", int(os.getenv("WW_ENERGY_CONSUMPTION")))
heating_heatpump_service = PanasonicAquareaService(db_service, int(os.getenv("RELAY_PIN_HEATING1")), int(os.getenv("RELAY_PIN_HEATING2")), "Panasonic Heating Heatpump", int(os.getenv("HEATING1_ENERGY_CONSUMPTION")), int(os.getenv("HEATING2_ENERGY_CONSUMPTION")))

STOP_CAR_CHARGING_WAIT_TIME = int(os.getenv("STOP_CAR_CHARGING_WAIT_TIME"))

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
        # sonnen_battery_service.refresh_status()  # Refresh the status to get the latest data

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
            ui.label(f"{charging_status.action.name} (since {charging_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Charger status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            charger_status = goe_service.get_charger_status()
            ui.label(f"{charger_status.name}").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Car status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            car_status = goe_service.get_car_status()
            ui.label(f"{car_status.name}").style("font-size: 16px; margin-top: 0px;")
            
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
            ui.label(f"{logic_mode.name}").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Configured phases / current").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ph = goe_service.get_phases()
            phases = "autom." if ph == 0 else str(ph)
            current = goe_service.get_charging_current()
            ui.label(f"{phases} / {current} A").style("font-size: 16px; margin-top: 0px;")

            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Charger error").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            charger_error = goe_service.get_error()
            ui.label(f"{charger_error.name}").style("font-size: 16px; margin-top: 0px;")
            
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
            ui.label(f"{ww_status.action.name} (since {ww_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
        
            # Heating Heatpump
            ui.label(f"{heating_heatpump_service.name}").style("font-size: 18px; font-weight: bold; margin-top: 20px;").classes("col-span-full")
            ui.label("").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            ui.label("Status").style("font-size: 16px; font-weight: bold; margin-top: 0px;")
            heating_status = db_service.get_heatpump_status_by_id(heating_heatpump_service.get_id())
            ui.label(f"{heating_status.action.name} (since {heating_status.timestamp.strftime('%Y-%m-%d, %H:%M:%S')})").style("font-size: 16px; margin-top: 0px;")
            
        with ui.header(elevated=True).style("background-color: #f0f0f0; padding: 10px;").classes("items-center justify-between"):
            ui.label("Energy Status Dashboard").style("font-size: 24px; font-weight: bold;color :#333;")
            
            energy_status = db_service.get_energy_status_time_series(60)  # Get energy status for the last 60 minutes
            if energy_status:
                # get list of production values from energy_status
                timestamps = [status.timestamp for status in energy_status]
                energy_productions = [status.production / 1000 for status in energy_status]
                energy_consumptions = [status.consumption / 1000 for status in energy_status]
                energy_feed_ins = [status.feed_in / 1000 for status in energy_status]
                
                fig = {
                    "data": [
                        {"x": timestamps, "y": energy_productions, "type": "line", "name": "Prod.", "line": {"color": "green"}},
                        {"x": timestamps, "y": energy_consumptions, "type": "line", "name": "Cons.", "line": {"color": "red"}},
                        {"x": timestamps, "y": energy_feed_ins, "type": "line", "name": "Avail.", "line": {"color": "blue"}},
                    ],
                    "layout": {
                        "margin": {"t": 0, "r": 0, "b": 18, "l": 40},
                        "plot_bgcolor": "#f8f8f8",
                        "paper_bgcolor": "#f0f0f0",
                        "yaxis": {"title": {"text": "Power (kW)"}}
                    },
                    "config": {
                        "staticPlot": True,
                        "displayModeBar": False,
                        "displaylogo": False
                    }
                }
                ui.plotly(fig).style("width: 100%; height: 130px; background-color: #f0f0f0; border: 0px solid #ddd; border-radius: 0px; padding: 0px;")
            else:
                ui.label("No energy data available").style("color: #666;")
            
        with ui.footer(elevated=True).style("background-color: #f0f0f0; padding: 10px;").classes("items-center justify-between"):
            # Fetch current energy production from the database
            energy_production = sonnen_battery_service.get_energy_production() / 1000
            energy_consumption = sonnen_battery_service.get_energy_consumption() / 1000
            available_energy = sonnen_battery_service.get_grid_feed() / 1000
            available_energy_min = sonnen_battery_service.get_grid_feed_in_minimum(STOP_CAR_CHARGING_WAIT_TIME) / 1000
            ui.label(f"Production: {energy_production} kW").style("color: #666;")
            ui.label(f"Consumption: {energy_consumption} kW").style("color: #666;")
            ui.label(f"Available: {available_energy} kW").style("color: #666;")
            ui.label(f"Min. Available ({STOP_CAR_CHARGING_WAIT_TIME} min): {available_energy_min} kW").style("color: #666;")
