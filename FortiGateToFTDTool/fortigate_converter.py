# FortiGate to Cisco FTD Configuration Converter - MAIN SCRIPT
# =============================================================
# This is the main script that orchestrates the conversion process.
# It loads the YAML file, calls the converter modules, and saves the output.

# This modular approach keeps the code organized and easier to maintain.

# REQUIREMENTS:
#     - Python 3.6 or higher
#     - PyYAML library (install with: pip install pyyaml)

# FILE STRUCTURE:
#     fortigate_converter.py          <- This main script (run this one!)
#     address_converter.py            <- Handles address object conversion
#     address_group_converter.py      <- Handles address group conversion
#     your_fortigate_config.yaml      <- Your FortiGate configuration file

# HOW TO RUN THIS SCRIPT:
#     1. Save ALL THREE Python files in the same folder
#     2. Place your FortiGate YAML file in the SAME FOLDER
#     3. Open terminal/command prompt and navigate to the folder:
#        cd C:\path\to\your\folder
#     4. Run the main script:
#        python fortigate_converter.py your_fortigate_config.yaml
    
#     EXAMPLES:
#     python fortigate_converter.py fortigate.yaml
#     python fortigate_converter.py fortigate.yaml -o output.json --pretty


import yaml
import json
import argparse
import sys
from pathlib import Path

# Import our custom converter modules
# These modules contain the logic for converting specific object types
try:
    from address_converter import AddressConverter
    from address_group_converter import AddressGroupConverter
    from service_converter import ServiceConverter
    from service_group_converter import ServiceGroupConverter
except ImportError as e:
    print("\n" + "="*60)
    print("ERROR: Missing converter module files!")
    print("="*60)
    print(f"\nDetails: {e}")
    print("\nMake sure these files are in the same folder as this script:")
    print("  1. address_converter.py")
    print("  2. address_group_converter.py")
    print("  3. service_converter.py")
    print("  4. service_group_converter.py")
    print("  5. fortigate_converter.py (this file)")
    print("\n" + "="*60)
    sys.exit(1)


def main():
    """
    Main function that orchestrates the entire conversion process.
    
    WORKFLOW:
    1. Parse command-line arguments (input file, output file, formatting)
    2. Load and parse the FortiGate YAML configuration file
    3. Initialize converter modules for each object type
    4. Convert address objects
    5. Convert address groups
    6. Combine all converted objects into one JSON structure
    7. Save the output JSON file
    8. Display a summary of what was converted
    
    Returns:
        0 on success, 1 on error
    """
    # ========================================================================
    # STEP 1: Set up command-line argument parser
    # ========================================================================
    # This allows users to customize how they run the script
    parser = argparse.ArgumentParser(
        description='Convert FortiGate YAML configuration to Cisco FTD FDM API JSON format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fortigate_converter.py fortigate.yaml
  python fortigate_converter.py fortigate.yaml -o output.json
  python fortigate_converter.py fortigate.yaml --pretty
  python fortigate_converter.py C:\\configs\\fortigate.yaml -o C:\\output\\ftd.json --pretty
        """
    )
    
    # REQUIRED argument: The FortiGate YAML file to convert
    parser.add_argument('input_file', 
                       help='Path to FortiGate YAML configuration file')
    
    # Optional argument: Where to save the output JSON (default: ftd_config.json)
    parser.add_argument('-o', '--output', 
                       help='Base name for output JSON files (default: ftd_config)',
                       default='ftd_config')
    
    # OPTIONAL flag: Make the JSON output human-readable with indentation
    parser.add_argument('-p', '--pretty', 
                       action='store_true',
                       help='Format JSON output with indentation for readability')
    
    # Parse the arguments that the user provided
    args = parser.parse_args()
    
    # ========================================================================
    # STEP 2: Display welcome banner
    # ========================================================================
    print("="*60)
    print("FortiGate to Cisco FTD Configuration Converter")
    print("="*60)
    
    # ========================================================================
    # STEP 3: Load the FortiGate YAML configuration file
    # ========================================================================
    print(f"\nLoading FortiGate configuration from: {args.input_file}")
    
    try:
        # Open the YAML file in read mode
        with open(args.input_file, 'r') as f:
            # Parse the YAML content into a Python dictionary
            # yaml.safe_load() safely parses YAML without executing code
            fg_config = yaml.safe_load(f)
        
        print("✓ YAML file loaded successfully")
        
    except FileNotFoundError:
        # This error occurs if the file doesn't exist at the specified path
        print(f"\n✗ ERROR: Input file '{args.input_file}' not found!")
        print("\nTroubleshooting:")
        print("  1. Check that the file path is correct")
        print("  2. If the file is in the same folder as this script, just use the filename")
        print("  3. If the file is elsewhere, provide the full path:")
        print("     Windows: C:\\path\\to\\file.yaml")
        print("     Mac/Linux: /path/to/file.yaml")
        return 1
        
    except yaml.YAMLError as e:
        # This error occurs if the YAML file has syntax errors
        print(f"\n✗ ERROR: Could not parse YAML file!")
        print(f"  Details: {e}")
        print("\nMake sure the file is valid YAML format")
        return 1
        
    except Exception as e:
        # Catch any other unexpected errors
        print(f"\n✗ ERROR: {e}")
        return 1
    
    # ========================================================================
    # STEP 4: Initialize converter modules
    # ========================================================================
    # Each converter module is responsible for one type of object
    print("\nInitializing converters...")
    
    # Create converter instances for address-related objects
    address_converter = AddressConverter(fg_config)
    address_group_converter = AddressGroupConverter(fg_config)
    
    # Create converter instances for service-related objects
    service_converter = ServiceConverter(fg_config)
    service_group_converter = ServiceGroupConverter(fg_config)
    
    # ========================================================================
    # STEP 5: Convert address objects
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Address Objects...")
    print("-"*60)
    
    # Call the convert() method to transform FortiGate addresses to FTD format
    # This returns a list of FTD network object dictionaries
    network_objects = address_converter.convert()
    
    print(f"✓ Converted {len(network_objects)} address objects")
    
    # ========================================================================
    # STEP 6: Convert address groups
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Address Groups...")
    print("-"*60)
    
    # Call the convert() method to transform FortiGate address groups to FTD format
    # This returns a list of FTD network group dictionaries
    network_groups = address_group_converter.convert()
    
    print(f"✓ Converted {len(network_groups)} address groups")
    
    # ========================================================================
    # STEP 7: Convert service port objects
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Service Port Objects...")
    print("-"*60)
    
    # Convert FortiGate services to FTD port objects
    # This handles splitting services with both TCP and UDP into separate objects
    port_objects = service_converter.convert()
    
    # Get statistics about the conversion
    service_stats = service_converter.get_statistics()
    print(f"✓ Converted {service_stats['total_objects']} port objects")
    print(f"  - TCP objects: {service_stats['tcp_objects']}")
    print(f"  - UDP objects: {service_stats['udp_objects']}")
    print(f"  - Services split into TCP+UDP: {service_stats['split_services']}")
    if service_stats['skipped_services'] > 0:
        print(f"  - Skipped (non-port protocols): {service_stats['skipped_services']}")
    
    # ========================================================================
    # STEP 8: Identify split services for group processing
    # ========================================================================
    # Build a set of service names that were split into TCP and UDP
    # This is needed so the group converter knows to expand these members
    split_services = set()
    
    # Look through all converted port objects to find pairs
    # If we have both "SERVICE_TCP" and "SERVICE_UDP", then "SERVICE" was split
    tcp_names = {obj['name'][:-4] for obj in port_objects if obj['name'].endswith('_TCP')}
    udp_names = {obj['name'][:-4] for obj in port_objects if obj['name'].endswith('_UDP')}
    split_services = tcp_names & udp_names  # Intersection of both sets
    
    if split_services:
        print(f"\n  Services split into TCP and UDP: {', '.join(sorted(split_services))}")
    
    # ========================================================================
    # STEP 9: Convert service port groups
    # ========================================================================
    print("\n" + "-"*60)
    print("Converting Service Port Groups...")
    print("-"*60)
    
    # Update the service group converter with the list of split services
    service_group_converter.set_split_services(split_services)
    
    # Convert FortiGate service groups to FTD port groups
    port_groups = service_group_converter.convert()
    
    print(f"✓ Converted {len(port_groups)} port groups")
    
    # ========================================================================
    # STEP 10: Organize converted objects into two separate structures
    # ========================================================================
    # ADDRESS-RELATED OBJECTS (network objects and groups)
    address_config = {
        "network_objects": network_objects,      # Individual address objects
        "network_groups": network_groups         # Address groups
    }
    
    # SERVICE-RELATED OBJECTS (port objects and groups)
    service_config = {
        "port_objects": port_objects,            # Individual port objects (TCP/UDP)
        "port_groups": port_groups               # Port groups
    }
    
    # ========================================================================
    # STEP 11: Write the output JSON files
    # ========================================================================
    print(f"\n" + "-"*60)
    print(f"Saving output files...")
    print("-"*60)
    
    # Generate output filenames based on the base name provided
    # If user specified "ftd_config", we create:
    #   - ftd_config_addresses.json
    #   - ftd_config_services.json
    address_output = f"{args.output}_addresses.json"
    service_output = f"{args.output}_services.json"
    
    try:
        # ====================================================================
        # Save address configuration
        # ====================================================================
        with open(address_output, 'w') as f:
            if args.pretty:
                json.dump(address_config, f, indent=2)
            else:
                json.dump(address_config, f)
        print(f"✓ Address configuration saved to: {address_output}")
        
        # ====================================================================
        # Save service configuration
        # ====================================================================
        with open(service_output, 'w') as f:
            if args.pretty:
                json.dump(service_config, f, indent=2)
            else:
                json.dump(service_config, f)
        print(f"✓ Service configuration saved to: {service_output}")
        
    except IOError as e:
        print(f"\n✗ ERROR: Could not write output files!")
        print(f"  Details: {e}")
        return 1
    
    # ========================================================================
    # STEP 12: Display final summary
    # ========================================================================
    print("\n" + "="*60)
    print("CONVERSION COMPLETE")
    print("="*60)
    print(f"\nAddress-Related Objects ({address_output}):")
    print(f"  Network Objects:    {len(network_objects)}")
    print(f"  Network Groups:     {len(network_groups)}")
    print(f"\nService-Related Objects ({service_output}):")
    print(f"  Port Objects:       {service_stats['total_objects']}")
    print(f"    - TCP:            {service_stats['tcp_objects']}")
    print(f"    - UDP:            {service_stats['udp_objects']}")
    print(f"  Port Groups:        {len(port_groups)}")
    print("\nNext steps:")
    print("  1. Review the generated JSON files")
    print("  2. Test with a small subset first")
    print("  3. Use FTD FDM API to import address objects first")
    print("  4. Then import service objects")
    print("  5. Finally import the groups (which reference the objects)")
    print("  6. Verify the configuration in FTD")
    print("\n" + "="*60)
    
    return 0

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

# This is the entry point of the script
# When you run "python fortigate_converter.py", execution starts here
if __name__ == '__main__':
    sys.exit(main())
